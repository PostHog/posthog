import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/kafka/producer'
import { createTestTeam } from '~/tests/helpers/team'
import { InternalPerson } from '~/types'
import { EventIngestionRestrictionManager, RestrictionType } from '~/utils/event-ingestion-restrictions'
import { parseJSON } from '~/utils/json-parse'
import { PromiseScheduler } from '~/utils/promise-scheduler'
import { TeamManager } from '~/utils/team-manager'
import { UUIDT } from '~/utils/utils'
import { GroupTypeManager } from '~/worker/ingestion/group-type-manager'
import { PersonRepository } from '~/worker/ingestion/persons/repositories/person-repository'

import { TophogOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { SingleIngestionOutput } from '../outputs/single-ingestion-output'
import { TopHogRegistry } from '../pipelines/extensions/tophog'
import { TopHog } from '../tophog'
import { CymbalClient } from './cymbal/client'
import { CymbalResponse } from './cymbal/types'
import { ErrorTrackingHogTransformer } from './error-tracking-consumer'
import {
    ErrorTrackingPipelineConfig,
    createErrorTrackingPipeline,
    runErrorTrackingPipeline,
} from './error-tracking-pipeline'

// Skip retry sleeps so tests run instantly
jest.mock('~/utils/utils', () => ({
    ...jest.requireActual('~/utils/utils'),
    sleep: jest.fn().mockResolvedValue(undefined),
}))

// Suppress logger output during tests
jest.mock('~/utils/logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

describe('ErrorTrackingPipeline', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockTeamManager: jest.Mocked<TeamManager>
    let mockPersonRepository: jest.Mocked<PersonRepository>
    let mockHogTransformer: jest.Mocked<ErrorTrackingHogTransformer>
    let mockCymbalClient: jest.Mocked<CymbalClient>
    let mockGroupTypeManager: jest.Mocked<GroupTypeManager>
    let mockEventIngestionRestrictionManager: jest.Mocked<EventIngestionRestrictionManager>
    let promiseScheduler: PromiseScheduler
    let pipelineConfig: ErrorTrackingPipelineConfig

    const team = createTestTeam({ id: 123, api_token: 'test-token-123' })

    const createTestPerson = (
        overrides: Partial<InternalPerson> & { distinct_id?: string } = {}
    ): InternalPerson & { distinct_id: string } => ({
        id: '1',
        uuid: 'person-uuid-123',
        team_id: 123,
        distinct_id: 'user-123', // Default matches createKafkaMessage default
        properties: { email: 'test@example.com', name: 'Test User' },
        is_user_id: null,
        is_identified: true,
        created_at: DateTime.utc(2024, 1, 1),
        version: 1,
        last_seen_at: null,
        properties_last_updated_at: {},
        properties_last_operation: null,
        ...overrides,
    })

    const createCymbalResponse = (overrides: Partial<CymbalResponse> = {}): CymbalResponse => ({
        uuid: 'test-uuid',
        event: '$exception',
        team_id: 1,
        timestamp: '2024-01-01T00:00:00Z',
        properties: {
            $exception_list: [{ type: 'Error', value: 'Test error' }],
            $exception_fingerprint: 'test-fingerprint',
            $exception_issue_id: 'test-issue-id',
        },
        ...overrides,
    })

    /**
     * Creates a mock Kafka message with proper headers and body structure.
     */
    const createKafkaMessage = (options: {
        token?: string
        distinctId?: string
        eventUuid?: string
        timestamp?: string
        ip?: string
        event?: string
        properties?: Record<string, any>
    }): Message => {
        const {
            token = 'test-token-123',
            distinctId = 'user-123',
            eventUuid = new UUIDT().toString(),
            timestamp = '2024-01-01T00:00:00Z',
            ip = '1.2.3.4',
            event = '$exception',
            properties = {},
        } = options

        const eventData = {
            event,
            distinct_id: distinctId,
            uuid: eventUuid,
            timestamp,
            ip,
            properties: {
                $exception_list: [{ type: 'Error', value: 'Test error' }],
                ...properties,
            },
        }

        const messageBody = {
            token,
            data: JSON.stringify(eventData),
            ...eventData,
        }

        return {
            value: Buffer.from(JSON.stringify(messageBody)),
            headers: [
                { token: Buffer.from(token) },
                { distinct_id: Buffer.from(distinctId) },
                { uuid: Buffer.from(eventUuid) },
                { timestamp: Buffer.from(timestamp) },
            ],
            topic: 'error_tracking_events',
            partition: 0,
            offset: 0,
            size: 0,
            key: Buffer.from(distinctId),
        } as Message
    }

    /**
     * Helper to get events produced to a specific topic.
     */
    const getProducedMessagesForTopic = (topic: string): any[] => {
        return mockKafkaProducer.produce.mock.calls
            .filter((call) => call[0].topic === topic)
            .map((call) => parseJSON(call[0].value!.toString()))
    }

    /**
     * Helper to get events that were produced to the output topic.
     */
    const getProducedEvents = (): any[] => {
        return getProducedMessagesForTopic('clickhouse_events_json_test')
    }

    /**
     * Helper to get events that were sent to the DLQ.
     */
    const getDLQMessages = (): any[] => {
        return getProducedMessagesForTopic('error_tracking_dlq')
    }

    /**
     * Helper to get events that were redirected to overflow.
     */
    const getOverflowMessages = (): any[] => {
        return getProducedMessagesForTopic('error_tracking_overflow')
    }

    /**
     * Helper to get ingestion warnings that were queued.
     * Ingestion warnings are sent via queueMessages to the ingestion_warnings topic.
     */
    const getIngestionWarnings = (): any[] => {
        return mockKafkaProducer.queueMessages.mock.calls
            .filter((call) => {
                const arg = call[0]
                // queueMessages can receive a single TopicMessage or an array
                const topicMessages = Array.isArray(arg) ? arg : [arg]
                return topicMessages.some((tm: any) => tm.topic?.includes('ingestion_warnings'))
            })
            .flatMap((call) => {
                const arg = call[0]
                const topicMessages = Array.isArray(arg) ? arg : [arg]
                return topicMessages
                    .filter((tm: any) => tm.topic?.includes('ingestion_warnings'))
                    .flatMap((tm: any) => tm.messages.map((m: { value: string }) => parseJSON(m.value)))
            })
    }

    /**
     * Creates a Cymbal response that includes enriched properties.
     * In real usage, Cymbal receives the enriched event and returns it with
     * fingerprint/issue_id added. This helper simulates that behavior.
     */
    const createCymbalResponseWithEnrichedProperties = (
        enrichedProperties: Record<string, any>,
        overrides: Partial<CymbalResponse> = {}
    ): CymbalResponse => ({
        uuid: 'test-uuid',
        event: '$exception',
        team_id: 1,
        timestamp: '2024-01-01T00:00:00Z',
        properties: {
            ...enrichedProperties,
            $exception_fingerprint: 'test-fingerprint',
            $exception_issue_id: 'test-issue-id',
        },
        ...overrides,
    })

    beforeEach(() => {
        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockReturnValue(Promise.resolve()),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<KafkaProducerWrapper>

        mockTeamManager = {
            getTeamByToken: jest.fn().mockResolvedValue(team),
            getTeam: jest.fn().mockResolvedValue(team),
        } as unknown as jest.Mocked<TeamManager>

        mockPersonRepository = {
            fetchPerson: jest.fn(),
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonsByPersonIds: jest.fn(),
            createPerson: jest.fn(),
            updatePerson: jest.fn(),
            updatePersonAssertVersion: jest.fn(),
            updatePersonsBatch: jest.fn(),
            deletePerson: jest.fn(),
            addDistinctId: jest.fn(),
            addPersonlessDistinctId: jest.fn(),
            addPersonlessDistinctIdForMerge: jest.fn(),
            addPersonlessDistinctIdsBatch: jest.fn(),
            personPropertiesSize: jest.fn(),
            updateCohortsAndFeatureFlagsForMerge: jest.fn(),
            inTransaction: jest.fn(),
        } as unknown as jest.Mocked<PersonRepository>

        // HogTransformer mock that passes through events unchanged by default
        mockHogTransformer = {
            start: jest.fn().mockResolvedValue(undefined),
            stop: jest.fn().mockResolvedValue(undefined),
            transformEventAndProduceMessages: jest
                .fn()
                .mockImplementation((event) => Promise.resolve({ event, invocationResults: [] })),
            processInvocationResults: jest.fn().mockResolvedValue(undefined),
        }

        mockCymbalClient = {
            processExceptions: jest.fn(),
            healthCheck: jest.fn(),
        } as unknown as jest.Mocked<CymbalClient>

        mockGroupTypeManager = {
            fetchGroupTypes: jest.fn().mockResolvedValue({}),
            fetchGroupTypeIndex: jest.fn(),
            insertGroupType: jest.fn(),
        } as unknown as jest.Mocked<GroupTypeManager>

        mockEventIngestionRestrictionManager = {
            getAppliedRestrictions: jest.fn().mockReturnValue(new Set()),
            forceRefresh: jest.fn(),
        } as unknown as jest.Mocked<EventIngestionRestrictionManager>

        promiseScheduler = new PromiseScheduler()

        // Mock TopHog registry that returns no-op recorders
        const mockRecorder = { record: jest.fn() }
        const mockTopHog: TopHogRegistry = {
            registerSum: () => mockRecorder,
            registerMax: () => mockRecorder,
            registerAverage: () => mockRecorder,
        }

        pipelineConfig = {
            outputs: new IngestionOutputs({
                events: new SingleIngestionOutput('events', 'clickhouse_events_json_test', mockKafkaProducer, 'test'),
                ingestion_warnings: new SingleIngestionOutput(
                    'ingestion_warnings',
                    'clickhouse_ingestion_warnings_test',
                    mockKafkaProducer,
                    'test'
                ),
                dlq: new SingleIngestionOutput('dlq', 'error_tracking_dlq', mockKafkaProducer, 'test'),
                overflow: new SingleIngestionOutput('overflow', 'error_tracking_overflow', mockKafkaProducer, 'test'),
                tophog: new SingleIngestionOutput('tophog', 'clickhouse_tophog_test', mockKafkaProducer, 'test'),
            }),
            groupId: 'error-tracking-test',
            promiseScheduler,
            teamManager: mockTeamManager,
            personRepository: mockPersonRepository,
            hogTransformer: mockHogTransformer,
            cymbalClient: mockCymbalClient,
            groupTypeManager: mockGroupTypeManager,
            eventIngestionRestrictionManager: mockEventIngestionRestrictionManager,
            overflowEnabled: false,
            topHog: mockTopHog,
        }
    })

    describe('createErrorTrackingPipeline', () => {
        it('creates a pipeline successfully', () => {
            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            expect(pipeline).toBeDefined()
            expect(typeof pipeline.feed).toBe('function')
            expect(typeof pipeline.next).toBe('function')
        })
    })

    describe('runErrorTrackingPipeline', () => {
        it('processes a single event through the full pipeline and emits to Kafka', async () => {
            const person = createTestPerson()
            mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValue([person])

            // Cymbal receives raw properties (no GeoIP yet) and adds fingerprint/issue_id
            const cymbalResponse = createCymbalResponseWithEnrichedProperties({
                $exception_list: [{ type: 'Error', value: 'Test error' }],
            })
            mockCymbalClient.processExceptions.mockResolvedValue([cymbalResponse])

            // Hog transformations run AFTER Cymbal and add GeoIP properties
            mockHogTransformer.transformEventAndProduceMessages.mockImplementation((event) =>
                Promise.resolve({
                    event: {
                        ...event,
                        properties: {
                            ...event.properties,
                            $geoip_country_code: 'US',
                            $geoip_city_name: 'San Francisco',
                            $geoip_subdivision_1_code: 'CA',
                            $geoip_subdivision_1_name: 'California',
                            $geoip_latitude: 37.7749,
                            $geoip_longitude: -122.4194,
                        },
                    },
                    invocationResults: [],
                })
            )

            const message = createKafkaMessage({})
            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Verify Hog transformations were run
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            // Verify event was emitted to Kafka
            const producedEvents = getProducedEvents()
            expect(producedEvents).toHaveLength(1)

            const emittedEvent = producedEvents[0]
            expect(emittedEvent.event).toBe('$exception')
            expect(emittedEvent.team_id).toBe(123)

            // Verify person fields are on the top-level event (not in properties)
            expect(emittedEvent.person_id).toBe('person-uuid-123')
            expect(parseJSON(emittedEvent.person_properties)).toEqual({
                email: 'test@example.com',
                name: 'Test User',
            })

            // Verify properties contain GeoIP (from Hog transformations) and Cymbal data
            const props = parseJSON(emittedEvent.properties)
            expect(props.$geoip_country_code).toBe('US')
            expect(props.$geoip_city_name).toBe('San Francisco')
            expect(props.$exception_fingerprint).toBe('test-fingerprint')
        })

        it('processes multiple events in a batch', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined) // No person

            const uuid1 = new UUIDT().toString()
            const uuid2 = new UUIDT().toString()

            const cymbalResponses = [
                createCymbalResponse({
                    uuid: uuid1,
                    properties: { $exception_fingerprint: 'fp-1', $exception_issue_id: 'issue-1' },
                }),
                createCymbalResponse({
                    uuid: uuid2,
                    properties: { $exception_fingerprint: 'fp-2', $exception_issue_id: 'issue-2' },
                }),
            ]
            mockCymbalClient.processExceptions.mockResolvedValue(cymbalResponses)

            const messages = [
                createKafkaMessage({ distinctId: 'user-1', eventUuid: uuid1 }),
                createKafkaMessage({ distinctId: 'user-2', eventUuid: uuid2 }),
            ]

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, messages)

            expect(mockCymbalClient.processExceptions).toHaveBeenCalledTimes(1)

            // Verify batch was sent to Cymbal
            const cymbalCall = mockCymbalClient.processExceptions.mock.calls[0][0]
            expect(cymbalCall).toHaveLength(2)

            // Verify Hog transformations were run for each event
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(2)

            // Verify both events were emitted
            const producedEvents = getProducedEvents()
            expect(producedEvents).toHaveLength(2)
        })

        it('passes Kafka message byte size to Cymbal for batch chunking', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            const cymbalResponse = createCymbalResponseWithEnrichedProperties({
                $exception_list: [{ type: 'Error', value: 'Test error' }],
            })
            mockCymbalClient.processExceptions.mockResolvedValue([cymbalResponse])

            const message = createKafkaMessage({})
            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            const cymbalItems = mockCymbalClient.processExceptions.mock.calls[0][0]
            expect(cymbalItems).toHaveLength(1)
            expect(cymbalItems[0].estimatedSize).toBe(message.value!.length)
        })

        it('handles events with group types', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            // Mock fetchGroupTypes to return the group type to index mapping
            mockGroupTypeManager.fetchGroupTypes.mockResolvedValue({
                company: 0,
                project: 1,
            })

            // Cymbal receives enriched properties (including $group_*) and returns them
            const cymbalResponse = createCymbalResponseWithEnrichedProperties({
                $exception_list: [{ type: 'Error', value: 'Test error' }],
                $groups: { company: 'acme-corp', project: 'project-123' },
                $group_0: 'acme-corp',
                $group_1: 'project-123',
            })
            mockCymbalClient.processExceptions.mockResolvedValue([cymbalResponse])

            const message = createKafkaMessage({
                properties: {
                    $groups: {
                        company: 'acme-corp',
                        project: 'project-123',
                    },
                },
            })

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Verify Hog transformations were run
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            const producedEvents = getProducedEvents()
            expect(producedEvents).toHaveLength(1)

            const props = parseJSON(producedEvents[0].properties)
            expect(props.$group_0).toBe('acme-corp')
            expect(props.$group_1).toBe('project-123')
        })

        it('suppresses events when Cymbal returns null response', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            // Cymbal returns null for suppressed events
            mockCymbalClient.processExceptions.mockResolvedValue([null])

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Suppressed events are dropped before Hog transformations run
            expect(mockHogTransformer.transformEventAndProduceMessages).not.toHaveBeenCalled()

            // Suppressed events are dropped, nothing emitted
            expect(getProducedEvents()).toHaveLength(0)
        })

        it('skips processing for empty input', async () => {
            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [])

            expect(mockCymbalClient.processExceptions).not.toHaveBeenCalled()
        })

        it('drops events with unknown team token', async () => {
            // Note: Invalid tokens are dropped silently (consistent with analytics pipeline).
            // This differs from billing restrictions which send to DLQ.
            mockTeamManager.getTeamByToken.mockResolvedValue(null)

            const message = createKafkaMessage({ token: 'unknown-token' })

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Events with unknown tokens are dropped before Cymbal or Hog transformations
            expect(mockCymbalClient.processExceptions).not.toHaveBeenCalled()
            expect(mockHogTransformer.transformEventAndProduceMessages).not.toHaveBeenCalled()

            // Event should not be produced anywhere (dropped silently)
            expect(getProducedEvents()).toHaveLength(0)
            expect(getDLQMessages()).toHaveLength(0)
            expect(getOverflowMessages()).toHaveLength(0)
        })

        it('sends events to DLQ when REDIRECT_TO_DLQ restriction is set', async () => {
            mockEventIngestionRestrictionManager.getAppliedRestrictions.mockReturnValue(
                new Set([RestrictionType.REDIRECT_TO_DLQ])
            )

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Events redirected to DLQ skip processing entirely
            expect(mockCymbalClient.processExceptions).not.toHaveBeenCalled()
            expect(mockHogTransformer.transformEventAndProduceMessages).not.toHaveBeenCalled()

            // Event should not be produced to output topic
            expect(getProducedEvents()).toHaveLength(0)

            // Event should be sent to DLQ
            const dlqMessages = getDLQMessages()
            expect(dlqMessages).toHaveLength(1)
            expect(dlqMessages[0].distinct_id).toBe('user-123')
        })

        it('drops events silently when DROP_EVENT restriction is set', async () => {
            mockEventIngestionRestrictionManager.getAppliedRestrictions.mockReturnValue(
                new Set([RestrictionType.DROP_EVENT])
            )

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Dropped events skip processing entirely
            expect(mockCymbalClient.processExceptions).not.toHaveBeenCalled()
            expect(mockHogTransformer.transformEventAndProduceMessages).not.toHaveBeenCalled()

            // Event should not be produced anywhere
            expect(getProducedEvents()).toHaveLength(0)
            expect(getDLQMessages()).toHaveLength(0)
            expect(getOverflowMessages()).toHaveLength(0)
        })

        it('redirects events to overflow when FORCE_OVERFLOW restriction is set', async () => {
            mockEventIngestionRestrictionManager.getAppliedRestrictions.mockReturnValue(
                new Set([RestrictionType.FORCE_OVERFLOW])
            )

            const message = createKafkaMessage({})

            // Enable overflow for this test
            const configWithOverflow: ErrorTrackingPipelineConfig = {
                ...pipelineConfig,
                overflowEnabled: true,
            }

            const pipeline = createErrorTrackingPipeline(configWithOverflow)
            await runErrorTrackingPipeline(pipeline, [message])

            // Events redirected to overflow skip processing entirely
            expect(mockCymbalClient.processExceptions).not.toHaveBeenCalled()
            expect(mockHogTransformer.transformEventAndProduceMessages).not.toHaveBeenCalled()

            // Event should not be produced to output topic
            expect(getProducedEvents()).toHaveLength(0)

            // Event should be redirected to overflow topic
            const overflowMessages = getOverflowMessages()
            expect(overflowMessages).toHaveLength(1)
            expect(overflowMessages[0].distinct_id).toBe('user-123')
        })

        it('processes events normally when FORCE_OVERFLOW is set but overflow is disabled', async () => {
            // When overflow is disabled, FORCE_OVERFLOW restriction is ignored and
            // events process normally. This allows graceful degradation.
            mockEventIngestionRestrictionManager.getAppliedRestrictions.mockReturnValue(
                new Set([RestrictionType.FORCE_OVERFLOW])
            )
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const message = createKafkaMessage({})

            // Overflow is disabled by default in pipelineConfig
            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Event should be processed normally including Hog transformations
            expect(mockCymbalClient.processExceptions).toHaveBeenCalledTimes(1)
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)
            expect(getProducedEvents()).toHaveLength(1)
            expect(getOverflowMessages()).toHaveLength(0)
        })

        it('propagates database errors from person lookup', async () => {
            mockPersonRepository.fetchPersonsByDistinctIds.mockRejectedValue(new Error('Database error'))
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)

            // Database errors should propagate up - they indicate infrastructure issues
            await expect(runErrorTrackingPipeline(pipeline, [message])).rejects.toThrow('Database error')

            // Cymbal was called but Hog transformations weren't reached due to person lookup failure
            expect(mockCymbalClient.processExceptions).toHaveBeenCalledTimes(1)
            expect(mockHogTransformer.transformEventAndProduceMessages).not.toHaveBeenCalled()
        })

        it('retries Cymbal errors and propagates after exhausting retries', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            // Create retriable error (default errors are treated as retriable)
            const retriableError = new Error('Cymbal unavailable')
            ;(retriableError as any).isRetriable = true
            mockCymbalClient.processExceptions.mockRejectedValue(retriableError)

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)

            // Cymbal errors are retried 10 times (pipeline default), then propagate
            // so Kafka doesn't commit and retries the batch
            await expect(runErrorTrackingPipeline(pipeline, [message])).rejects.toThrow('Cymbal unavailable')

            // Cymbal was called 10 times (initial + 9 retries) before giving up
            expect(mockCymbalClient.processExceptions).toHaveBeenCalledTimes(10)
            expect(mockHogTransformer.transformEventAndProduceMessages).not.toHaveBeenCalled()
        })

        it('retries Cymbal errors and succeeds on subsequent attempts', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            // First two calls fail with retriable error, third call succeeds
            const retriableError = new Error('Cymbal temporarily unavailable')
            ;(retriableError as any).isRetriable = true

            mockCymbalClient.processExceptions
                .mockRejectedValueOnce(retriableError)
                .mockRejectedValueOnce(retriableError)
                .mockResolvedValueOnce([createCymbalResponse()])

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Cymbal was called 3 times before succeeding
            expect(mockCymbalClient.processExceptions).toHaveBeenCalledTimes(3)
            // Processing continued after Cymbal succeeded
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)
            // Event was emitted
            expect(getProducedEvents()).toHaveLength(1)
        })

        it('sends events to DLQ on non-retriable Cymbal errors', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            // Non-retriable error (e.g., 400 Bad Request from Cymbal)
            const nonRetriableError = new Error('Bad request - invalid event format')
            ;(nonRetriableError as any).isRetriable = false
            mockCymbalClient.processExceptions.mockRejectedValue(nonRetriableError)

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Non-retriable errors should not be retried
            expect(mockCymbalClient.processExceptions).toHaveBeenCalledTimes(1)
            // Processing should not continue past Cymbal
            expect(mockHogTransformer.transformEventAndProduceMessages).not.toHaveBeenCalled()
            // Event should not be produced to output topic
            expect(getProducedEvents()).toHaveLength(0)
            // Event should be sent to DLQ
            const dlqMessages = getDLQMessages()
            expect(dlqMessages).toHaveLength(1)
        })

        it('sends all batch events to DLQ on non-retriable Cymbal error', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            // Non-retriable error affects the entire batch
            const nonRetriableError = new Error('Bad request - invalid batch')
            ;(nonRetriableError as any).isRetriable = false
            mockCymbalClient.processExceptions.mockRejectedValue(nonRetriableError)

            const messages = [
                createKafkaMessage({ distinctId: 'user-1' }),
                createKafkaMessage({ distinctId: 'user-2' }),
                createKafkaMessage({ distinctId: 'user-3' }),
            ]

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, messages)

            // Non-retriable errors should not be retried
            expect(mockCymbalClient.processExceptions).toHaveBeenCalledTimes(1)
            // All events should be sent to DLQ
            const dlqMessages = getDLQMessages()
            expect(dlqMessages).toHaveLength(3)
            // No events should be produced to output topic
            expect(getProducedEvents()).toHaveLength(0)
        })

        it('runs Hog transformations on events', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Verify the transformer was called
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            const producedEvents = getProducedEvents()
            expect(producedEvents).toHaveLength(1)
        })

        it('preserves GeoIP properties added by Hog transformations', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            // Mock the transformer to add GeoIP properties (simulating the GeoIP transformation)
            mockHogTransformer.transformEventAndProduceMessages.mockImplementation((event) =>
                Promise.resolve({
                    event: {
                        ...event,
                        properties: {
                            ...event.properties,
                            $geoip_country_code: 'US',
                            $geoip_city_name: 'San Francisco',
                            $geoip_subdivision_1_code: 'CA',
                            $geoip_subdivision_1_name: 'California',
                            $geoip_latitude: 37.7749,
                            $geoip_longitude: -122.4194,
                        },
                    },
                    invocationResults: [],
                })
            )

            const message = createKafkaMessage({ ip: '89.160.20.129' })

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            const producedEvents = getProducedEvents()
            expect(producedEvents).toHaveLength(1)

            const props = parseJSON(producedEvents[0].properties)
            expect(props.$geoip_country_code).toBe('US')
            expect(props.$geoip_city_name).toBe('San Francisco')
            expect(props.$geoip_subdivision_1_code).toBe('CA')
            expect(props.$geoip_subdivision_1_name).toBe('California')
            expect(props.$geoip_latitude).toBe(37.7749)
            expect(props.$geoip_longitude).toBe(-122.4194)
        })

        it('preserves original event properties through enrichment', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            // Cymbal receives original properties and returns them with fingerprint/issue_id
            const cymbalResponse = createCymbalResponseWithEnrichedProperties({
                $exception_list: [{ type: 'Error', value: 'Test error' }],
                custom_property: 'should-be-preserved',
                $browser: 'Chrome',
            })
            mockCymbalClient.processExceptions.mockResolvedValue([cymbalResponse])

            const message = createKafkaMessage({
                properties: {
                    custom_property: 'should-be-preserved',
                    $browser: 'Chrome',
                },
            })

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Verify Hog transformations were run
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            const producedEvents = getProducedEvents()
            expect(producedEvents).toHaveLength(1)
            const props = parseJSON(producedEvents[0].properties)
            expect(props.custom_property).toBe('should-be-preserved')
            expect(props.$browser).toBe('Chrome')
        })

        it('emits ingestion warning when Cymbal returns $cymbal_errors', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            const eventUuid = new UUIDT().toString()

            // Cymbal returns event with processing errors attached
            const cymbalResponse = createCymbalResponse({
                uuid: eventUuid,
                properties: {
                    $exception_list: [{ type: 'Error', value: 'Test error' }],
                    $exception_fingerprint: 'test-fingerprint',
                    $exception_issue_id: 'test-issue-id',
                    $cymbal_errors: [
                        'No sourcemap found for source url: https://example.com/app.js',
                        'Token not found for frame: app.js:10:5',
                    ],
                },
            })
            mockCymbalClient.processExceptions.mockResolvedValue([cymbalResponse])

            const message = createKafkaMessage({ eventUuid })

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Event should still be emitted (errors don't block processing)
            const producedEvents = getProducedEvents()
            expect(producedEvents).toHaveLength(1)

            // Verify ingestion warning was sent
            const warnings = getIngestionWarnings()
            expect(warnings).toHaveLength(1)
            expect(warnings[0].type).toBe('error_tracking_exception_processing_errors')
            expect(warnings[0].team_id).toBe(123)

            const details = parseJSON(warnings[0].details)
            expect(details.eventUuid).toBe(eventUuid)
            expect(details.errors).toEqual([
                'No sourcemap found for source url: https://example.com/app.js',
                'Token not found for frame: app.js:10:5',
            ])
        })

        it('does not emit ingestion warning when Cymbal returns no errors', async () => {
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)

            // Cymbal returns event without errors
            const cymbalResponse = createCymbalResponse({
                properties: {
                    $exception_list: [{ type: 'Error', value: 'Test error' }],
                    $exception_fingerprint: 'test-fingerprint',
                    $exception_issue_id: 'test-issue-id',
                    // No $cymbal_errors
                },
            })
            mockCymbalClient.processExceptions.mockResolvedValue([cymbalResponse])

            const message = createKafkaMessage({})

            const pipeline = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline, [message])

            // Event should be emitted
            const producedEvents = getProducedEvents()
            expect(producedEvents).toHaveLength(1)

            // No ingestion warning should be sent
            const warnings = getIngestionWarnings()
            expect(warnings).toHaveLength(0)
        })

        it('always uses full person_mode to preserve group properties', async () => {
            // Error tracking always uses processPerson=true to preserve $group_* properties,
            // unlike the analytics pipeline which may use propertyless mode.

            // Test with person found - should be 'full' mode
            const person = createTestPerson()
            mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValue([person])
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const pipeline1 = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline1, [createKafkaMessage({})])

            // Verify Hog transformations were run
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            let producedEvents = getProducedEvents()
            expect(producedEvents[0].person_mode).toBe('full')

            // Reset mocks
            mockKafkaProducer.produce.mockClear()
            mockHogTransformer.transformEventAndProduceMessages.mockClear()

            // Test without person found - still uses 'full' mode because processPerson=true
            mockPersonRepository.fetchPerson.mockResolvedValue(undefined)
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const pipeline2 = createErrorTrackingPipeline(pipelineConfig)
            await runErrorTrackingPipeline(pipeline2, [createKafkaMessage({ distinctId: 'no-person' })])

            // Verify Hog transformations were run for second pipeline too
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            producedEvents = getProducedEvents()
            // Error tracking sets processPerson=true so it's always 'full' mode
            expect(producedEvents[0].person_mode).toBe('full')
        })
    })

    describe('TopHog metrics', () => {
        let mockTophogQueueMessages: jest.Mock
        let topHog: TopHog

        beforeEach(() => {
            mockTophogQueueMessages = jest.fn().mockResolvedValue(undefined)
            const tophogOutputs = {
                queueMessages: mockTophogQueueMessages,
            } as unknown as IngestionOutputs<TophogOutput>

            topHog = new TopHog({
                outputs: tophogOutputs,
                pipeline: 'error_tracking',
                lane: 'main',
            })
        })

        const getTopHogMessages = (): any[] => {
            return mockTophogQueueMessages.mock.calls.flatMap((call: any) =>
                call[1].map((m: any) => parseJSON(m.value.toString()))
            )
        }

        it('records resolved_teams metric when team is resolved', async () => {
            const person = createTestPerson()
            mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValue([person])
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const configWithTopHog: ErrorTrackingPipelineConfig = {
                ...pipelineConfig,
                topHog,
            }

            const pipeline = createErrorTrackingPipeline(configWithTopHog)
            await runErrorTrackingPipeline(pipeline, [createKafkaMessage({})])
            await topHog.flush()

            // Verify Hog transformations were run
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            const messages = getTopHogMessages()
            const resolvedTeamsMetric = messages.find((m) => m.metric === 'resolved_teams')
            expect(resolvedTeamsMetric).toBeDefined()
            expect(resolvedTeamsMetric.type).toBe('sum')
            expect(resolvedTeamsMetric.key.team_id).toBe('123')
            expect(resolvedTeamsMetric.value).toBe(1)
        })

        it('records emitted_events metric when events are emitted', async () => {
            const person = createTestPerson()
            mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValue([person])
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const configWithTopHog: ErrorTrackingPipelineConfig = {
                ...pipelineConfig,
                topHog,
            }

            const pipeline = createErrorTrackingPipeline(configWithTopHog)
            await runErrorTrackingPipeline(pipeline, [createKafkaMessage({})])
            await topHog.flush()

            // Verify Hog transformations were run
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            const messages = getTopHogMessages()
            const emittedEventsMetric = messages.find((m) => m.metric === 'emitted_events')
            expect(emittedEventsMetric).toBeDefined()
            expect(emittedEventsMetric.type).toBe('sum')
            expect(emittedEventsMetric.key.team_id).toBe('123')
            expect(emittedEventsMetric.value).toBe(1)
        })

        it('records emitted_events_per_distinct_id metric with distinct_id', async () => {
            const person = createTestPerson()
            mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValue([person])
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const configWithTopHog: ErrorTrackingPipelineConfig = {
                ...pipelineConfig,
                topHog,
            }

            const pipeline = createErrorTrackingPipeline(configWithTopHog)
            await runErrorTrackingPipeline(pipeline, [createKafkaMessage({ distinctId: 'specific-user' })])
            await topHog.flush()

            // Verify Hog transformations were run
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            const messages = getTopHogMessages()
            const perDistinctIdMetric = messages.find((m) => m.metric === 'emitted_events_per_distinct_id')
            expect(perDistinctIdMetric).toBeDefined()
            expect(perDistinctIdMetric.type).toBe('sum')
            expect(perDistinctIdMetric.key.team_id).toBe('123')
            expect(perDistinctIdMetric.key.distinct_id).toBe('specific-user')
            expect(perDistinctIdMetric.value).toBe(1)
        })

        it('includes pipeline and lane labels in TopHog output', async () => {
            const person = createTestPerson()
            mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValue([person])
            mockCymbalClient.processExceptions.mockResolvedValue([createCymbalResponse()])

            const configWithTopHog: ErrorTrackingPipelineConfig = {
                ...pipelineConfig,
                topHog,
            }

            const pipeline = createErrorTrackingPipeline(configWithTopHog)
            await runErrorTrackingPipeline(pipeline, [createKafkaMessage({})])
            await topHog.flush()

            // Verify Hog transformations were run
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)

            const messages = getTopHogMessages()
            expect(messages.length).toBeGreaterThan(0)
            for (const msg of messages) {
                expect(msg.pipeline).toBe('error_tracking')
                expect(msg.lane).toBe('main')
            }
        })

        it('aggregates metrics across multiple events', async () => {
            const person = createTestPerson()
            mockPersonRepository.fetchPersonsByDistinctIds.mockResolvedValue([person])
            mockCymbalClient.processExceptions.mockImplementation((events) =>
                Promise.resolve(events.map(() => createCymbalResponse()))
            )

            const configWithTopHog: ErrorTrackingPipelineConfig = {
                ...pipelineConfig,
                topHog,
            }

            const messages = [
                createKafkaMessage({ distinctId: 'user-1' }),
                createKafkaMessage({ distinctId: 'user-2' }),
                createKafkaMessage({ distinctId: 'user-1' }),
            ]

            const pipeline = createErrorTrackingPipeline(configWithTopHog)
            await runErrorTrackingPipeline(pipeline, messages)
            await topHog.flush()

            // Verify Hog transformations were run for all events
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(3)

            const topHogMessages = getTopHogMessages()

            // resolved_teams should have count=3 (one per event)
            const resolvedTeamsMetric = topHogMessages.find((m) => m.metric === 'resolved_teams')
            expect(resolvedTeamsMetric.value).toBe(3)

            // emitted_events should have value=3
            const emittedEventsMetric = topHogMessages.find((m) => m.metric === 'emitted_events')
            expect(emittedEventsMetric.value).toBe(3)

            // emitted_events_per_distinct_id should have two entries (user-1 with 2, user-2 with 1)
            const perDistinctIdMetrics = topHogMessages.filter((m) => m.metric === 'emitted_events_per_distinct_id')
            const user1Metric = perDistinctIdMetrics.find((m) => m.key.distinct_id === 'user-1')
            const user2Metric = perDistinctIdMetrics.find((m) => m.key.distinct_id === 'user-2')
            expect(user1Metric.value).toBe(2)
            expect(user2Metric.value).toBe(1)
        })
    })
})
