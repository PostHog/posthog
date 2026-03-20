import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KafkaConsumer } from '~/kafka/consumer'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, PipelineEvent, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { parseJSON } from '~/utils/json-parse'
import { UUIDT } from '~/utils/utils'
import { PersonRepository } from '~/worker/ingestion/persons/repositories/person-repository'

import { ErrorTrackingConsumer, ErrorTrackingHogTransformer } from './error-tracking-consumer'

/** Creates a mock KafkaConsumer for tests that don't need actual Kafka connections */
const createMockKafkaConsumer = (): jest.Mocked<Pick<KafkaConsumer, 'connect' | 'disconnect' | 'isHealthy'>> => ({
    connect: jest.fn().mockResolvedValue(undefined),
    disconnect: jest.fn().mockResolvedValue(undefined),
    isHealthy: jest.fn().mockReturnValue({ status: 'ok' }),
})

jest.setTimeout(60000)

jest.mock('../../utils/posthog', () => {
    const original = jest.requireActual('../../utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

// Mock the IngestionWarningLimiter to always allow warnings
jest.mock('../../utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        ...jest.requireActual('../../utils/token-bucket'),
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

// Mock the logger to reduce noise
jest.mock('../../utils/logger', () => ({
    logger: {
        debug: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
    },
}))

// Create a mock PersonRepository to avoid database schema issues
const createMockPersonRepository = (): jest.Mocked<PersonRepository> => ({
    fetchPerson: jest.fn().mockResolvedValue(undefined),
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
})

// Mock the CymbalClient to avoid real HTTP calls
// Cymbal receives event properties and returns them with fingerprint/issue_id added
jest.mock('./cymbal', () => ({
    CymbalClient: jest.fn().mockImplementation(() => ({
        processExceptions: jest.fn().mockImplementation((requests) =>
            // Return a valid response for each request, preserving input properties
            requests.map((req: any) => ({
                uuid: req.uuid,
                event: req.event,
                team_id: req.team_id,
                timestamp: req.timestamp,
                properties: {
                    ...req.properties,
                    $exception_fingerprint: `fingerprint-${req.uuid}`,
                    $exception_issue_id: `issue-${req.uuid}`,
                },
            }))
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
    let hub: Hub
    let team: Team
    let fixedTime: DateTime
    let mockHogTransformer: jest.Mocked<ErrorTrackingHogTransformer>

    const createConsumer = async (hub: Hub) => {
        const config = {
            groupId: hub.ERROR_TRACKING_CONSUMER_GROUP_ID,
            topic: hub.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC,
            dlqTopic: hub.ERROR_TRACKING_CONSUMER_DLQ_TOPIC,
            overflowTopic: hub.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC,
            outputTopic: hub.ERROR_TRACKING_CONSUMER_OUTPUT_TOPIC,
            cymbalBaseUrl: hub.ERROR_TRACKING_CYMBAL_BASE_URL,
            cymbalTimeoutMs: hub.ERROR_TRACKING_CYMBAL_TIMEOUT_MS,
            lane: hub.INGESTION_LANE ?? ('main' as const),
            overflowBucketCapacity: hub.ERROR_TRACKING_OVERFLOW_BUCKET_CAPACITY,
            overflowBucketReplenishRate: hub.ERROR_TRACKING_OVERFLOW_BUCKET_REPLENISH_RATE,
            statefulOverflowEnabled: hub.ERROR_TRACKING_STATEFUL_OVERFLOW_ENABLED,
            statefulOverflowRedisTTLSeconds: hub.ERROR_TRACKING_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
            statefulOverflowLocalCacheTTLSeconds: hub.ERROR_TRACKING_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
            pipeline: hub.INGESTION_PIPELINE ?? 'error_tracking',
        }
        // Create and store the mock so tests can configure it
        mockHogTransformer = createMockHogTransformer()
        const deps = {
            kafkaProducer: hub.kafkaProducer,
            kafkaMetricsProducer: hub.kafkaProducer,
            teamManager: hub.teamManager,
            hogTransformer: mockHogTransformer,
            groupTypeManager: hub.groupTypeManager,
            redisPool: hub.redisPool,
            personRepository: hub.personRepository,
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
        hub = await createHub()
        team = await getFirstTeam(hub.postgres)

        // Replace the real personRepository with a mock to avoid database schema issues
        // (the test database may be missing the last_seen_at column)
        hub.personRepository = createMockPersonRepository()

        consumer = await createConsumer(hub)
    })

    afterEach(async () => {
        await consumer.stop()
        await closeHub(hub)
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
            expect(consumer['config'].dlqTopic).toBe('ingestion-errortracking-main-dlq_test')
            expect(consumer['config'].outputTopic).toBe('clickhouse_events_json_test')
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
