import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { PipelineEvent, ProjectId, Team, TimestampFormat } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { castTimestampOrNow } from '../../utils/utils'
import {
    EventPipelineResult,
    EventPipelineRunner,
    EventPipelineRunnerOptions,
} from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
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

const createTestEventPipelineResult = (): EventPipelineResult => ({
    lastStep: 'test-step',
    person: {
        team_id: 1,
        properties: {},
        uuid: 'person-uuid',
        created_at: castTimestampOrNow('2023-01-01T00:00:00.000Z', TimestampFormat.ISO) as any,
        force_upgrade: false,
    },
    preparedEvent: {
        eventUuid: 'test-uuid',
        event: 'test-event',
        teamId: 1,
        projectId: 1 as ProjectId,
        distinctId: 'test-distinct-id',
        properties: {},
        timestamp: castTimestampOrNow('2023-01-01T00:00:00.000Z', TimestampFormat.ISO),
    },
    processPerson: true,
    historicalMigration: false,
})

describe('event-pipeline-runner-v1-step', () => {
    let mockConfig: EventPipelineRunnerOptions
    let mockKafkaProducer: KafkaProducerWrapper
    let mockTeamManager: TeamManager
    let mockGroupTypeManager: GroupTypeManager
    let mockHogTransformer: HogTransformerService
    let mockPersonsStore: PersonsStore
    let mockGroupStore: GroupStoreForBatch
    let mockEventPipelineRunner: jest.Mocked<EventPipelineRunner>
    let mockMessage: Message
    let mockEvent: PipelineEvent
    let mockTeam: Team
    let mockHeaders: any

    beforeEach(() => {
        jest.clearAllMocks()

        mockConfig = {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
            TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: 0,
            PIPELINE_STEP_STALLED_LOG_TIMEOUT: 30000,
            PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 100,
            PERSON_MERGE_ASYNC_ENABLED: false,
            PERSON_MERGE_ASYNC_TOPIC: '',
            PERSON_MERGE_SYNC_BATCH_SIZE: 1,
            PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
            PERSON_PROPERTIES_UPDATE_ALL: false,
        }
        mockKafkaProducer = {} as KafkaProducerWrapper
        mockTeamManager = {} as TeamManager
        mockGroupTypeManager = {} as GroupTypeManager
        mockHogTransformer = {} as HogTransformerService
        mockPersonsStore = {} as PersonsStore
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
            const mockResult = createTestEventPipelineResult()
            const ackPromise = Promise.resolve()
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult, [ackPromise])
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            const result = await step(input)
            expect(EventPipelineRunner).toHaveBeenCalledWith(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockEvent,
                mockHogTransformer,
                mockPersonsStore,
                mockGroupStore,
                mockHeaders
            )
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, true, false)
            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.sideEffects).toEqual([ackPromise])
            if (result.type === PipelineResultType.OK) {
                expect(result.value.inputHeaders).toBe(mockHeaders)
                expect(result.value.inputMessage).toBe(mockMessage)
            }
        })

        it('should handle retriable errors by re-throwing them', async () => {
            const retriableError = new Error('Retriable error')
            ;(retriableError as any).isRetriable = true
            mockEventPipelineRunner.runEventPipeline.mockRejectedValue(retriableError)

            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            await expect(step(input)).rejects.toThrow('Retriable error')
        })

        it('should handle non-retriable errors by re-throwing them', async () => {
            const nonRetriableError = new Error('Non-retriable error')
            ;(nonRetriableError as any).isRetriable = false
            mockEventPipelineRunner.runEventPipeline.mockRejectedValue(nonRetriableError)

            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            await expect(step(input)).rejects.toThrow('Non-retriable error')
        })

        it('should handle errors without isRetriable property by re-throwing them', async () => {
            const errorWithoutRetriable = new Error('Error without isRetriable')
            mockEventPipelineRunner.runEventPipeline.mockRejectedValue(errorWithoutRetriable)

            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            await expect(step(input)).rejects.toThrow('Error without isRetriable')
        })

        it('should handle successful pipeline results with side effects', async () => {
            const ackPromise1 = Promise.resolve()
            const ackPromise2 = Promise.resolve('kafka-ack')
            const ackPromise3 = Promise.resolve({ clickhouse: 'ack' })
            const sideEffects = [ackPromise1, ackPromise2, ackPromise3]
            const mockResult = createTestEventPipelineResult()
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult, sideEffects)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            const result = await step(input)
            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.sideEffects).toEqual(sideEffects)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.inputHeaders).toBe(mockHeaders)
                expect(result.value.inputMessage).toBe(mockMessage)
            }
        })

        it('should handle successful pipeline results without side effects', async () => {
            const mockResult = createTestEventPipelineResult()
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            const result = await step(input)
            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.sideEffects).toEqual([])
            if (result.type === PipelineResultType.OK) {
                expect(result.value.inputHeaders).toBe(mockHeaders)
                expect(result.value.inputMessage).toBe(mockMessage)
            }
        })

        it('should pass all required parameters to EventPipelineRunner constructor', async () => {
            const mockResult = createTestEventPipelineResult()
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            await step(input)
            expect(EventPipelineRunner).toHaveBeenCalledTimes(1)
            expect(EventPipelineRunner).toHaveBeenCalledWith(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockEvent,
                mockHogTransformer,
                mockPersonsStore,
                mockGroupStore,
                mockHeaders
            )
        })

        it('should call runEventPipeline with correct parameters', async () => {
            const mockResult = createTestEventPipelineResult()
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)

            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledTimes(1)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, true, false)
        })
    })

    describe('processPerson and forceDisablePersonProcessing flags', () => {
        beforeEach(() => {
            const mockResult = createTestEventPipelineResult()
            const mockPipelineResult: PipelineResult<EventPipelineResult> = ok(mockResult)
            mockEventPipelineRunner.runEventPipeline.mockResolvedValue(mockPipelineResult)
        })

        it('should pass processPerson=false and forceDisablePersonProcessing=true to runEventPipeline', async () => {
            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: false,
                forceDisablePersonProcessing: true,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, false, true)
        })

        it('should pass processPerson=true and forceDisablePersonProcessing=false to runEventPipeline', async () => {
            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: false,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, true, false)
        })

        it('should pass processPerson=false and forceDisablePersonProcessing=false to runEventPipeline', async () => {
            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: false,
                forceDisablePersonProcessing: false,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, false, false)
        })

        it('should pass processPerson=true and forceDisablePersonProcessing=true to runEventPipeline', async () => {
            const step = createEventPipelineRunnerV1Step(
                mockConfig,
                mockKafkaProducer,
                mockTeamManager,
                mockGroupTypeManager,
                mockHogTransformer,
                mockPersonsStore
            )
            const input: EventPipelineRunnerInput = {
                message: mockMessage,
                event: mockEvent,
                team: mockTeam,
                headers: mockHeaders,
                groupStoreForBatch: mockGroupStore,
                processPerson: true,
                forceDisablePersonProcessing: true,
            }

            await step(input)
            expect(mockEventPipelineRunner.runEventPipeline).toHaveBeenCalledWith(mockEvent, mockTeam, true, true)
        })
    })
})
