import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { KafkaConsumer } from '~/common/kafka/consumer/consumer-v1'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { IngestionTestInfra, createIngestionTestInfra } from '~/tests/helpers/ingestion-e2e'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { PipelineEvent, Team } from '~/types'

import { ErrorTrackingConsumer, ErrorTrackingHogTransformer } from './error-tracking-consumer'

/** Creates a mock KafkaConsumer for tests that don't need actual Kafka connections */
const createMockKafkaConsumer = (): jest.Mocked<Pick<KafkaConsumer, 'connect' | 'disconnect' | 'isHealthy'>> => ({
    connect: jest.fn().mockResolvedValue(undefined),
    disconnect: jest.fn().mockResolvedValue(undefined),
    isHealthy: jest.fn().mockReturnValue({ status: 'ok' }),
})

jest.setTimeout(60000)

jest.mock('~/common/utils/posthog', () => {
    const original = jest.requireActual('~/common/utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

// Mock the IngestionWarningLimiter to always allow warnings
jest.mock('~/common/utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        ...jest.requireActual('~/common/utils/token-bucket'),
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

// Mock the logger to reduce noise
jest.mock('~/common/utils/logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

const createMockPersonRepository = (): jest.Mocked<PersonReadRepository> => ({
    fetchPerson: jest.fn().mockResolvedValue(undefined),
    fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
    fetchPersonsByPersonIds: jest.fn().mockResolvedValue([]),
    fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
})

// Mock the CymbalClient to avoid real HTTP calls
// Cymbal receives event properties and returns them with fingerprint/issue_id added
jest.mock('./cymbal', () => ({
    CymbalClient: jest.fn().mockImplementation(() => ({
        processExceptions: jest.fn().mockImplementation((items) =>
            items.map((item: any) => {
                const signature = (item.request.properties?.$exception_list ?? [])
                    .flatMap((exc: any) => exc?.stacktrace?.frames ?? [])
                    .map((frame: any) => frame?.function ?? '')
                    .join('|')
                const issueKey = signature || item.request.uuid
                return {
                    uuid: item.request.uuid,
                    event: item.request.event,
                    team_id: item.request.team_id,
                    timestamp: item.request.timestamp,
                    properties: {
                        ...item.request.properties,
                        $exception_fingerprint: `fingerprint-${issueKey}`,
                        $exception_issue_id: `issue-${issueKey}`,
                    },
                }
            })
        ),
    })),
}))

// Create a mock HogTransformerService that passes through events unchanged
const createMockHogTransformer = (): jest.Mocked<ErrorTrackingHogTransformer> => ({
    start: jest.fn().mockResolvedValue(undefined),
    stop: jest.fn().mockResolvedValue(undefined),
    transformEventAndProduceMessages: jest
        .fn()
        .mockImplementation((event) => Promise.resolve({ event, invocationResults: [] })),
    processInvocationResults: jest.fn().mockResolvedValue(undefined),
})

let offsetIncrementer = 0

const createKafkaMessage = (event: PipelineEvent, token: string): Message => {
    const captureEvent = {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        ip: event.ip,
        now: event.now,
        token,
        data: JSON.stringify(event),
    }
    return {
        key: `${token}:${event.distinct_id}`,
        value: Buffer.from(JSON.stringify(captureEvent)),
        size: 1,
        topic: 'error_tracking_events_test',
        offset: offsetIncrementer++,
        timestamp: DateTime.now().toMillis(),
        partition: 1,
        headers: [
            { distinct_id: Buffer.from(event.distinct_id || '') },
            { token: Buffer.from(token) },
            { event: Buffer.from(event.event || '') },
            { uuid: Buffer.from(event.uuid || '') },
            { now: Buffer.from(event.now || '') },
        ],
    }
}

describe('ErrorTrackingConsumer', () => {
    let consumer: ErrorTrackingConsumer
    let infra: IngestionTestInfra
    let team: Team
    let fixedTime: DateTime
    let mockHogTransformer: jest.Mocked<ErrorTrackingHogTransformer>

    const createConsumer = async (infra: IngestionTestInfra) => {
        const config = {
            groupId: infra.config.ERROR_TRACKING_CONSUMER_GROUP_ID,
            topic: infra.config.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC,
            cymbalBaseUrl: infra.config.ERROR_TRACKING_CYMBAL_BASE_URL,
            cymbalTimeoutMs: infra.config.ERROR_TRACKING_CYMBAL_TIMEOUT_MS,
            cymbalMaxBodyBytes: infra.config.ERROR_TRACKING_CYMBAL_MAX_BODY_BYTES,
            lane: infra.config.INGESTION_LANE ?? ('main' as const),
            overflowMode: infra.config.INGESTION_OVERFLOW_MODE,
            overflowBucketCapacity: infra.config.ERROR_TRACKING_OVERFLOW_BUCKET_CAPACITY,
            overflowBucketReplenishRate: infra.config.ERROR_TRACKING_OVERFLOW_BUCKET_REPLENISH_RATE,
            statefulOverflowRedisTTLSeconds: infra.config.ERROR_TRACKING_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
            statefulOverflowLocalCacheTTLSeconds: infra.config.ERROR_TRACKING_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
            preservePartitionLocality: infra.config.ERROR_TRACKING_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
            pipeline: infra.config.INGESTION_PIPELINE ?? 'errortracking',
        }
        // Create and store the mock so tests can configure it
        mockHogTransformer = createMockHogTransformer()
        const deps = {
            outputs: new IngestionOutputs({
                events: new SingleIngestionOutput(
                    'events',
                    infra.config.ERROR_TRACKING_CONSUMER_OUTPUT_TOPIC,
                    mockProducer,
                    'test'
                ),
                ingestion_warnings: new SingleIngestionOutput(
                    'ingestion_warnings',
                    'clickhouse_ingestion_warnings_test',
                    mockProducer,
                    'test'
                ),
                dlq: new SingleIngestionOutput(
                    'dlq',
                    infra.config.ERROR_TRACKING_CONSUMER_DLQ_TOPIC,
                    mockProducer,
                    'test'
                ),
                overflow: new SingleIngestionOutput(
                    'overflow',
                    infra.config.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC || '',
                    mockProducer,
                    'test'
                ),
                tophog: new SingleIngestionOutput('tophog', 'clickhouse_tophog_test', mockProducer, 'test'),
                app_metrics: new SingleIngestionOutput(
                    'app_metrics',
                    'clickhouse_app_metrics2_test',
                    mockProducer,
                    'test'
                ),
            }),
            teamManager: infra.teamManager,
            hogTransformer: mockHogTransformer,
            groupTypeManager: new ReadOnlyGroupTypeManager({
                fetchGroupsByKeys: jest.fn().mockResolvedValue([]),
                fetchGroupTypesByTeamIds: jest.fn().mockResolvedValue({}),
                fetchGroupTypesByProjectIds: jest.fn().mockResolvedValue({}),
            }),
            cookielessManager: infra.cookielessManager,
            redisPool: infra.redisPool,
            personRepository: createMockPersonRepository(),
        }
        const consumer = new ErrorTrackingConsumer(config, deps)
        // Replace Kafka consumer with mock to avoid actual connections
        consumer['kafkaConsumer'] = createMockKafkaConsumer() as unknown as KafkaConsumer
        await consumer.start()
        return consumer
    }

    const createEvent = (event?: Partial<PipelineEvent>): PipelineEvent => ({
        distinct_id: 'user-1',
        uuid: new UUIDT().toString(),
        ip: '127.0.0.1',
        site_url: 'us.posthog.com',
        now: fixedTime.toISO()!,
        event: '$exception',
        ...event,
        properties: {
            $exception_list: [
                {
                    type: 'Error',
                    value: 'Test error message',
                    mechanism: { type: 'generic', handled: true },
                },
            ],
            ...(event?.properties || {}),
        },
    })

    const createKafkaMessages = (events: PipelineEvent[], token?: string): Message[] => {
        return events.map((event) => createKafkaMessage(event, token ?? team.api_token))
    }

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        jest.spyOn(Date.prototype, 'toISOString').mockReturnValue(fixedTime.toISO()!)

        offsetIncrementer = 0
        await resetTestDatabase()
        infra = await createIngestionTestInfra()
        team = await getFirstTeam(infra.postgres)

        consumer = await createConsumer(infra)
    })

    afterEach(async () => {
        await consumer.stop()
        await infra.close()
        mockProducerObserver.resetKafkaProducer()
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('configuration', () => {
        it('should have correct config defaults', () => {
            expect(consumer['name']).toBe('error-tracking-consumer')
            expect(consumer['config'].groupId).toBe('ingestion-errortracking')
            expect(consumer['config'].topic).toBe('ingestion-errortracking-main_test')
        })
    })

    describe('event processing', () => {
        it('should process a basic exception event', async () => {
            const messages = createKafkaMessages([createEvent()])
            await consumer.handleKafkaBatch(messages)

            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages).toHaveLength(1)

            const event = producedMessages[0].value
            expect(event.event).toBe('$exception')
            expect(event.team_id).toBe(team.id)
            expect(event.distinct_id).toBe('user-1')
        })

        it('should process multiple exception events', async () => {
            const events = [
                createEvent({ distinct_id: 'user-1' }),
                createEvent({ distinct_id: 'user-2' }),
                createEvent({ distinct_id: 'user-3' }),
            ]
            const messages = createKafkaMessages(events)
            await consumer.handleKafkaBatch(messages)

            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages).toHaveLength(3)

            const distinctIds = producedMessages.map((m) => m.value.distinct_id).sort()
            expect(distinctIds).toEqual(['user-1', 'user-2', 'user-3'])
        })

        it('should include exception fingerprint and issue id from Cymbal', async () => {
            const messages = createKafkaMessages([createEvent()])
            await consumer.handleKafkaBatch(messages)

            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages).toHaveLength(1)

            const properties = parseJSON(producedMessages[0].value.properties as string)
            // Cymbal adds fingerprint and issue_id to processed events
            expect(properties.$exception_fingerprint).toBeDefined()
            expect(properties.$exception_issue_id).toBeDefined()
        })

        it('should preserve group properties', async () => {
            const messages = createKafkaMessages([
                createEvent({
                    properties: {
                        $exception_list: [{ type: 'Error', value: 'Test' }],
                        $groups: {
                            company: 'acme-corp',
                        },
                    },
                }),
            ])
            await consumer.handleKafkaBatch(messages)

            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages).toHaveLength(1)

            const properties = parseJSON(producedMessages[0].value.properties as string)
            // Group properties should be preserved (mapped to $group_0)
            expect(properties.$groups).toEqual({ company: 'acme-corp' })
        })

        it('should run Hog transformations on events', async () => {
            // Configure the mock to add GeoIP properties (simulating the GeoIP transformation)
            mockHogTransformer.transformEventAndProduceMessages.mockImplementation((event) =>
                Promise.resolve({
                    event: {
                        ...event,
                        properties: {
                            ...event.properties,
                            $geoip_country_code: 'SE',
                            $geoip_city_name: 'Linköping',
                        },
                    },
                    invocationResults: [],
                })
            )

            const messages = createKafkaMessages([
                createEvent({
                    ip: '89.160.20.129',
                }),
            ])
            await consumer.handleKafkaBatch(messages)

            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages).toHaveLength(1)

            // Verify Hog transformations were called and added GeoIP properties
            expect(mockHogTransformer.transformEventAndProduceMessages).toHaveBeenCalledTimes(1)
            const properties = parseJSON(producedMessages[0].value.properties as string)
            expect(properties.$geoip_country_code).toBe('SE')
            expect(properties.$geoip_city_name).toBe('Linköping')
        })

        it('should flush invocation results after batch processing', async () => {
            const messages = createKafkaMessages([createEvent()])
            await consumer.handleKafkaBatch(messages)

            expect(mockHogTransformer.processInvocationResults).toHaveBeenCalledTimes(1)
        })

        it('should flush invocation results even when batch processing fails', async () => {
            // Make the pipeline throw an error
            mockHogTransformer.transformEventAndProduceMessages.mockRejectedValueOnce(new Error('Test error'))

            const messages = createKafkaMessages([createEvent()])
            await expect(consumer.handleKafkaBatch(messages)).rejects.toThrow('Test error')

            // processInvocationResults should still be called via finally block
            expect(mockHogTransformer.processInvocationResults).toHaveBeenCalledTimes(1)
        })
    })

    describe('error handling', () => {
        it('should reject events with invalid token', async () => {
            const messages = createKafkaMessages([createEvent()], 'invalid-token-that-does-not-exist')
            await consumer.handleKafkaBatch(messages)

            // Event should not be produced to output topic (team not found = dropped)
            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages).toHaveLength(0)

            // Invalid token events are dropped (not DLQ'd) by the resolve team step
            // This is consistent with how the ingestion pipeline handles unknown tokens
        })

        it('should handle empty batch', async () => {
            await consumer.handleKafkaBatch([])

            const producedMessages = mockProducerObserver.getProducedKafkaMessages()
            expect(producedMessages).toHaveLength(0)
        })
    })

    describe('person properties', () => {
        it('should always use full person_mode', async () => {
            // Error tracking always uses full person_mode to preserve group properties
            const messages = createKafkaMessages([createEvent()])
            await consumer.handleKafkaBatch(messages)

            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages).toHaveLength(1)
            expect(producedMessages[0].value.person_mode).toBe('full')
        })
    })
})
