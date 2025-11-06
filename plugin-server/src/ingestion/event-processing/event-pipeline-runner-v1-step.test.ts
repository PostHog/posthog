import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Hub, JwtVerificationStatus, PipelineEvent, ProjectId, RawKafkaEvent, Team, TimestampFormat } from '../../types'
import { castTimestampOrNow } from '../../utils/utils'
import { EventPipelineResult, EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStoreForBatch } from '../../worker/ingestion/persons/persons-store-for-batch'
import { PipelineResult, PipelineResultType, ok } from '../pipelines/results'
import { EventPipelineRunnerInput, createEventPipelineRunnerV1Step } from './event-pipeline-runner-v1-step'

jest.mock('../../worker/ingestion/event-pipeline/runner', () => ({
    EventPipelineRunner: jest.fn(),
}))

jest.mock('../../utils/retries', () => ({
    retryIfRetriable: jest.fn((fn) => fn()),
}))

jest.mock('../../utils/logger', () => ({
    logger: {
        error: jest.fn(),
    },
}))

jest.mock('../../utils/posthog', () => ({
    captureException: jest.fn(),
}))

const createTestTeam = (overrides: Partial<Team> = {}): Team => ({
    id: 1,
    project_id: 1 as ProjectId,
    organization_id: 'test-org-id',
    uuid: v4(),
    name: 'Test Team',
    anonymize_ips: false,
    api_token: 'test-api-token',
    slack_incoming_webhook: null,
    session_recording_opt_in: true,
    person_processing_opt_out: null,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
    ...overrides,
})

const createTestRawKafkaEvent = (overrides: Partial<RawKafkaEvent> = {}): RawKafkaEvent => {
    const testTimestamp = castTimestampOrNow('2023-01-01T00:00:00.000Z', TimestampFormat.ClickHouse)
    return {
        uuid: 'test-uuid',
        event: 'test-event',
        properties: JSON.stringify({ test: 'property' }),
        timestamp: testTimestamp,
        team_id: 1,
        project_id: 1 as ProjectId,
        distinct_id: 'test-distinct-id',
        elements_chain: '',
        created_at: testTimestamp,
        person_id: 'person-uuid',
        person_properties: JSON.stringify({}),
        person_created_at: testTimestamp,
        person_mode: 'full',
        ...overrides,
    }
}

describe('event-pipeline-runner-v1-step', () => {
    let mockHub: Hub
    let mockHogTransformer: HogTransformerService
    let mockPersonsStore: PersonsStoreForBatch
    let mockGroupStore: GroupStoreForBatch
    let mockEventPipelineRunner: jest.Mocked<EventPipelineRunner>
    let mockMessage: Message
    let mockEvent: PipelineEvent
    let mockTeam: Team
    let mockHeaders: any

    beforeEach(() => {
        jest.clearAllMocks()

        mockHub = {} as Hub
        mockHogTransformer = {} as HogTransformerService
        mockPersonsStore = {} as PersonsStoreForBatch
        mockGroupStore = {} as GroupStoreForBatch

        mockMessage = {
            value: Buffer.from('test message'),
            key: Buffer.from('test key'),
            headers: {},
            partition: 0,
            offset: 123,
            timestamp: Date.now(),
        } as Message

        mockEvent = {
            uuid: 'test-uuid',
            event: 'test-event',
            distinct_id: 'test-distinct-id',
            properties: { test: 'property' },
            timestamp: '2023-01-01T00:00:00.000Z',
            ip: '127.0.0.1',
            site_url: 'https://test.com',
            now: '2023-01-01T00:00:00.000Z',
        } as PipelineEvent

        mockTeam = createTestTeam()

        mockHeaders = {
            token: 'test-token',
        }

        mockEventPipelineRunner = {
            runEventPipeline: jest.fn(),
        } as any

        jest.mocked(EventPipelineRunner).mockImplementation(() => mockEventPipelineRunner)
    })

    describe('createEventPipelineRunnerV1Step', () => {
        it('should create a step function that processes events successfully', async () => {
            const mockRawEvent = createTestRawKafkaEvent()
            const mockResult: EventPipelineResult = {
                lastStep: 'test-step',
                eventToEmit: mockRawEvent,
            }
            const ackPromise = Promise.resolve()
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult, [ackPromise])
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            const result = await step(input)
            expect(EventPipelineRunner).toHaveBeenCalledWith(
                mockHub,
                mockEvent,
                mockHogTransformer,
                mockPersonsStore,
                mockGroupStore,
                mockHeaders
            )
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, true, false)
            expect(result).toBe(mockPipelineResult)
            // Verify side effects are present
            expect(result.sideEffects).toEqual([ackPromise])
        })

        it('should handle retriable errors by re-throwing them', async () => {
            const retriableError = new Error('Retriable error')
            ;(retriableError as any).isRetriable = true
            mockEventPipelineRunner.runEventPipeline.mockRejectedValue(retriableError)

            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            await expect(step(input)).rejects.toThrow('Retriable error')
        })

        it('should handle non-retriable errors by re-throwing them', async () => {
            const nonRetriableError = new Error('Non-retriable error')
            ;(nonRetriableError as any).isRetriable = false
            mockEventPipelineRunner.runEventPipeline.mockRejectedValue(nonRetriableError)

            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            await expect(step(input)).rejects.toThrow('Non-retriable error')
        })

        it('should handle errors without isRetriable property by re-throwing them', async () => {
            const errorWithoutRetriable = new Error('Error without isRetriable')
            mockEventPipelineRunner.runEventPipeline.mockRejectedValue(errorWithoutRetriable)

            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            await expect(step(input)).rejects.toThrow('Error without isRetriable')
        })

        it('should handle successful pipeline results with side effects', async () => {
            const ackPromise1 = Promise.resolve()
            const ackPromise2 = Promise.resolve('kafka-ack')
            const ackPromise3 = Promise.resolve({ clickhouse: 'ack' })
            const sideEffects = [ackPromise1, ackPromise2, ackPromise3]
            const mockRawEvent = createTestRawKafkaEvent()
            const mockResult: EventPipelineResult = {
                lastStep: 'test-step',
                eventToEmit: mockRawEvent,
            }
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult, sideEffects)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            const result = await step(input)
            expect(result).toBe(mockPipelineResult)
            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.sideEffects).toEqual(sideEffects)
        })

        it('should handle successful pipeline results without side effects', async () => {
            const mockRawEvent = createTestRawKafkaEvent()
            const mockResult: EventPipelineResult = {
                lastStep: 'test-step',
                eventToEmit: mockRawEvent,
            }
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            const result = await step(input)
            expect(result).toBe(mockPipelineResult)
            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.sideEffects).toEqual([])
        })

        it('should pass all required parameters to EventPipelineRunner constructor', async () => {
            const mockRawEvent = createTestRawKafkaEvent()
            const mockResult: EventPipelineResult = {
                lastStep: 'test-step',
                eventToEmit: mockRawEvent,
            }
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            await step(input)
            expect(EventPipelineRunner).toHaveBeenCalledTimes(1)
            expect(EventPipelineRunner).toHaveBeenCalledWith(
                mockHub,
                mockEvent,
                mockHogTransformer,
                mockPersonsStore,
                mockGroupStore,
                mockHeaders
            )
        })

        it('should call runEventPipeline with correct parameters', async () => {
            const mockRawEvent = createTestRawKafkaEvent()
            const mockResult: EventPipelineResult = {
                lastStep: 'test-step',
                eventToEmit: mockRawEvent,
            }
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledTimes(1)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, true, false)
        })
    })

    describe('processPerson and forceDisablePersonProcessing flags', () => {
        beforeEach(() => {
            const mockRawEvent = createTestRawKafkaEvent()
            const mockResult: EventPipelineResult = {
                lastStep: 'test-step',
                eventToEmit: mockRawEvent,
            }
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)
        })

        it('should pass processPerson=false and forceDisablePersonProcessing=true to runEventPipeline', async () => {
            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: false,
                forceDisablePersonProcessing: true,
                verified: JwtVerificationStatus.NotVerified,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, false, true)
        })

        it('should pass processPerson=true and forceDisablePersonProcessing=false to runEventPipeline', async () => {
            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, true, false)
        })

        it('should pass processPerson=false and forceDisablePersonProcessing=false to runEventPipeline', async () => {
            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: false,
                forceDisablePersonProcessing: false,
                verified: JwtVerificationStatus.NotVerified,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, false, false)
        })

        it('should pass processPerson=true and forceDisablePersonProcessing=true to runEventPipeline', async () => {
            const step = createEventPipelineRunnerV1Step(mockHub, mockHogTransformer)
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                personsStoreForBatch: mockPersonsStore,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: true,
                verified: JwtVerificationStatus.NotVerified,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, true, true)
        })
    })
})
