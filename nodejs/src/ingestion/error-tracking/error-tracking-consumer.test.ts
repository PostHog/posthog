import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KafkaConsumer } from '~/kafka/consumer/consumer-v1'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, PipelineEvent, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'
import { ErrorTrackingSettingsManager } from '~/utils/error-tracking-settings-manager'
import { parseJSON } from '~/utils/json-parse'
import { UUIDT } from '~/utils/utils'
import { PersonRepository } from '~/worker/ingestion/persons/repositories/person-repository'

import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { SingleIngestionOutput } from '../outputs/single-ingestion-output'
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
        processExceptions: jest.fn().mockImplementation((items) =>
            // Return a valid response for each item, preserving input properties
            items.map((item: any) => ({
                uuid: item.request.uuid,
                event: item.request.event,
                team_id: item.request.team_id,
                timestamp: item.request.timestamp,
                properties: {
                    ...item.request.properties,
                    $exception_fingerprint: `fingerprint-${item.request.uuid}`,
                    $exception_issue_id: `issue-${item.request.uuid}`,
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
    let hub: Hub
    let team: Team
    let fixedTime: DateTime
    let mockHogTransformer: jest.Mocked<ErrorTrackingHogTransformer>

    const createConsumer = async (hub: Hub) => {
        const config = {
            groupId: hub.ERROR_TRACKING_CONSUMER_GROUP_ID,
            topic: hub.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC,
            cymbalBaseUrl: hub.ERROR_TRACKING_CYMBAL_BASE_URL,
            cymbalTimeoutMs: hub.ERROR_TRACKING_CYMBAL_TIMEOUT_MS,
            cymbalMaxBodyBytes: hub.ERROR_TRACKING_CYMBAL_MAX_BODY_BYTES,
            lane: hub.INGESTION_LANE ?? ('main' as const),
            overflowEnabled:
                !!hub.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC &&
                hub.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC !== hub.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC,
            overflowBucketCapacity: hub.ERROR_TRACKING_OVERFLOW_BUCKET_CAPACITY,
            overflowBucketReplenishRate: hub.ERROR_TRACKING_OVERFLOW_BUCKET_REPLENISH_RATE,
            statefulOverflowEnabled: hub.ERROR_TRACKING_STATEFUL_OVERFLOW_ENABLED,
            statefulOverflowRedisTTLSeconds: hub.ERROR_TRACKING_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
            statefulOverflowLocalCacheTTLSeconds: hub.ERROR_TRACKING_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
            preservePartitionLocality: hub.ERROR_TRACKING_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
            pipeline: hub.INGESTION_PIPELINE ?? 'errortracking',
            rateLimiterEnabled: hub.ERROR_TRACKING_RATE_LIMITER_ENABLED,
            rateLimiterReportingMode: hub.ERROR_TRACKING_RATE_LIMITER_REPORTING_MODE,
            rateLimiterRedisHost: hub.ERROR_TRACKING_RATE_LIMITER_REDIS_HOST,
            rateLimiterRedisPort: hub.ERROR_TRACKING_RATE_LIMITER_REDIS_PORT,
            rateLimiterRedisTls: hub.ERROR_TRACKING_RATE_LIMITER_REDIS_TLS,
            rateLimiterTtlSeconds: hub.ERROR_TRACKING_RATE_LIMITER_TTL_SECONDS,
            fallbackRedisUrl: hub.REDIS_URL,
            rateLimiterRedisPoolMinSize: hub.REDIS_POOL_MIN_SIZE,
            rateLimiterRedisPoolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        }
        // Create and store the mock so tests can configure it
        mockHogTransformer = createMockHogTransformer()
        const deps = {
            outputs: new IngestionOutputs({
                events: new SingleIngestionOutput(
                    'events',
                    hub.ERROR_TRACKING_CONSUMER_OUTPUT_TOPIC,
                    mockProducer,
                    'test'
                ),
                ingestion_warnings: new SingleIngestionOutput(
                    'ingestion_warnings',
                    'clickhouse_ingestion_warnings_test',
                    mockProducer,
                    'test'
                ),
                dlq: new SingleIngestionOutput('dlq', hub.ERROR_TRACKING_CONSUMER_DLQ_TOPIC, mockProducer, 'test'),
                overflow: new SingleIngestionOutput(
                    'overflow',
                    hub.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC || '',
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
            teamManager: hub.teamManager,
            errorTrackingSettingsManager: new ErrorTrackingSettingsManager(hub.postgres),
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

    describe('rate limiting', () => {
        const upsertSettings = async (args: {
            projectRateLimit?: number | null
            perIssueRateLimit?: number | null
        }): Promise<void> => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_errortrackingsettings
                    (team_id, project_rate_limit_value, project_rate_limit_bucket_size_minutes,
                     per_issue_rate_limit_value, per_issue_rate_limit_bucket_size_minutes)
                 VALUES ($1, $2, 60, $3, 60)
                 ON CONFLICT (team_id) DO UPDATE SET
                    project_rate_limit_value = EXCLUDED.project_rate_limit_value,
                    project_rate_limit_bucket_size_minutes = EXCLUDED.project_rate_limit_bucket_size_minutes,
                    per_issue_rate_limit_value = EXCLUDED.per_issue_rate_limit_value,
                    per_issue_rate_limit_bucket_size_minutes = EXCLUDED.per_issue_rate_limit_bucket_size_minutes`,
                [team.id, args.projectRateLimit ?? null, args.perIssueRateLimit ?? null],
                'test-upsert-error-tracking-settings'
            )
        }

        const enableRateLimiter = async (): Promise<void> => {
            await consumer.stop()
            hub.ERROR_TRACKING_RATE_LIMITER_ENABLED = true
            hub.ERROR_TRACKING_RATE_LIMITER_REPORTING_MODE = false
            consumer = await createConsumer(hub)

            await consumer['rateLimiterRedis']!.useClient({ name: 'test-flush' }, async (client) => {
                const keys = await client.keys(
                    `@posthog-test/error-tracking-rate-limiter/tokens/${team.id}:exceptions:*`
                )
                if (keys.length > 0) {
                    await client.del(...keys)
                }
            })
        }

        const exceptionEvent = (fn: string, value: string = 'msg'): PipelineEvent =>
            createEvent({
                properties: {
                    $exception_list: [
                        {
                            type: 'TypeError',
                            value,
                            stacktrace: { frames: [{ function: fn, filename: `${fn}.js`, lineno: 1 }] },
                            mechanism: { type: 'generic', handled: true },
                        },
                    ],
                },
            })

        const drainProduces = () => consumer['promiseScheduler'].waitForAll()

        const producedCount = (): number =>
            mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test').length

        // The Lua script reads time via `Date.now()`. `beforeEach` mocks it to a
        // fixed value; bumping the same spy advances "now" so the bucket refills.
        const advanceTime = (seconds: number): void => {
            jest.spyOn(Date, 'now').mockReturnValue(Date.now() + seconds * 1000)
        }

        describe('project rate limit', () => {
            it('lets early batches through and partially passes through once the budget is exhausted', async () => {
                await upsertSettings({ projectRateLimit: 15 })
                await enableRateLimiter()

                const sendBatch = (size: number) => {
                    const events = Array.from({ length: size }, (_, i) => exceptionEvent(`fn-${i}`))
                    return consumer.handleKafkaBatch(createKafkaMessages(events))
                }

                // tokens 15 → 5 (10 allowed)
                await sendBatch(10)
                // budget 5, batch of 30 → partial pass-through: 5 allowed, 25 dropped.
                await sendBatch(30)
                // bucket drained — entire batch dropped.
                await sendBatch(20)
                await drainProduces()

                expect(producedCount()).toBe(15)
            })

            it('refills tokens over time once the bucket window has elapsed', async () => {
                await upsertSettings({ projectRateLimit: 4 })
                await enableRateLimiter()

                const send = (fn: string) => consumer.handleKafkaBatch(createKafkaMessages([exceptionEvent(fn)]))

                // Team-keyed bucket drains regardless of signature.
                // tokens 4 → 3
                await send('foo')
                // 3 → 2
                await send('bar')
                // 2 → 1
                await send('baz')
                // 1 → 0 — last token spent, request served
                await send('qux')
                await drainProduces()
                expect(producedCount()).toBe(4)

                // Advance one full bucket window (60 min); refillRate = 4 / 3600s → bucket back to full.
                advanceTime(60 * 60)

                // tokens 4 → 3
                await send('foo')
                await drainProduces()
                expect(producedCount()).toBe(5)
            })
        })

        describe('per-issue rate limit', () => {
            it('partially passes through a batch that overflows multiple per-issue buckets', async () => {
                await upsertSettings({ perIssueRateLimit: 3 })
                await enableRateLimiter()

                // Single batch carrying two interleaved signatures, each with its own
                // bucket of 3. Per-input fan-out should allow 3 from each and drop the
                // overflow within each key group independently.
                const events = [
                    ...Array.from({ length: 12 }, () => exceptionEvent('foo')),
                    ...Array.from({ length: 12 }, () => exceptionEvent('bar')),
                ]
                await consumer.handleKafkaBatch(createKafkaMessages(events))
                await drainProduces()

                // 3 allowed per signature × 2 signatures = 6.
                expect(producedCount()).toBe(6)
            })

            it('applies independently to each stack signature', async () => {
                await upsertSettings({ perIssueRateLimit: 4 })
                await enableRateLimiter()

                const send = (fn: string) => consumer.handleKafkaBatch(createKafkaMessages([exceptionEvent(fn)]))

                // issue A: tokens 4 → 3
                await send('A')
                // 3 → 2
                await send('A')
                // 2 → 1
                await send('A')
                // 1 → 0 — last token spent, request served
                await send('A')
                // bucket empty — next A is dropped
                await send('A')

                expect(producedCount()).toBe(4)

                // issue B has its own fresh bucket: 4 → 3
                await send('B')
                await drainProduces()

                expect(producedCount()).toBe(5) // 4 from A + 1 from B
            })

            it('groups by stack and ignores message interpolation', async () => {
                await upsertSettings({ perIssueRateLimit: 4 })
                await enableRateLimiter()

                const send = (fn: string, value: string = 'msg') =>
                    consumer.handleKafkaBatch(createKafkaMessages([exceptionEvent(fn, value)]))

                // foo: tokens 4 → 3
                await send('foo')
                // 3 → 2
                await send('foo')
                // 2 → 1
                await send('foo')
                // 1 → 0 — last token spent, request served
                await send('foo')

                // bar has its own bucket: 4 → 3
                await send('bar')

                expect(producedCount()).toBe(5)

                // foo with different `value` → same key as foo's burst (value is
                // dropped from the hash when a stack exists) → bucket already empty,
                // request denied.
                await send('foo', 'different')
                await drainProduces()

                expect(producedCount()).toBe(5)
            })

            it('refills tokens over time once the bucket window has elapsed', async () => {
                await upsertSettings({ perIssueRateLimit: 4 })
                await enableRateLimiter()

                const send = (fn: string) => consumer.handleKafkaBatch(createKafkaMessages([exceptionEvent(fn)]))

                // tokens 4 → 3
                await send('foo')
                // 3 → 2
                await send('foo')
                // 2 → 1
                await send('foo')
                // 1 → 0 — last token spent, request served
                await send('foo')
                await drainProduces()
                expect(producedCount()).toBe(4)

                // Advance one full bucket window (60 min); refillRate = 4 / 3600s → bucket back to full.
                advanceTime(60 * 60)

                // tokens 4 → 3
                await send('foo')
                await drainProduces()
                expect(producedCount()).toBe(5)
            })
        })
    })
})
