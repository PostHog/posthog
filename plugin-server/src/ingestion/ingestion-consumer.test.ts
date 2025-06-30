// eslint-disable-next-line simple-import-sort/imports
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { insertHogFunction as _insertHogFunction } from '~/cdp/_tests/fixtures'
import { template as geoipTemplate } from '~/cdp/templates/_transformations/geoip/geoip.template'
import { compileHog } from '~/cdp/templates/compiler'
import { DecodedKafkaMessage } from '~/tests/helpers/mocks/producer.spy'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { CookielessServerHashMode, Hub, IncomingEventWithTeam, PipelineEvent, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { HogFunctionType } from '../cdp/types'
import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'
import { UUIDT } from '../utils/utils'
import { IngestionConsumer } from './ingestion-consumer'

import { COOKIELESS_MODE_FLAG_PROPERTY, COOKIELESS_SENTINEL_VALUE } from '~/ingestion/cookieless/cookieless-manager'
import { PostgresUse } from '../utils/db/postgres'
const DEFAULT_TEST_TIMEOUT = 5000
jest.setTimeout(DEFAULT_TEST_TIMEOUT)

jest.mock('../utils/posthog', () => {
    const original = jest.requireActual('../utils/posthog')
    return {
        ...original,
        captureException: jest.fn(),
    }
})

let offsetIncrementer = 0

const createKafkaMessage = (event: PipelineEvent): Message => {
    // TRICKY: This is the slightly different format that capture sends
    const captureEvent = {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        ip: event.ip,
        now: event.now,
        token: event.token,
        data: JSON.stringify(event),
    }
    return {
        key: `${event.token}:${event.distinct_id}`,
        value: Buffer.from(JSON.stringify(captureEvent)),
        size: 1,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: DateTime.now().toMillis(),
        partition: 1,
    }
}

const createKafkaMessages: (events: PipelineEvent[]) => Message[] = (events) => {
    return events.map(createKafkaMessage)
}

const createIncomingEventsWithTeam = (events: PipelineEvent[], team: Team): IncomingEventWithTeam[] => {
    return events.map<IncomingEventWithTeam>(
        (e): IncomingEventWithTeam => ({
            event: {
                ...e,
                team_id: team.id,
            },
            team: team,
            message: createKafkaMessage(e),
        })
    )
}

describe('IngestionConsumer', () => {
    let ingester: IngestionConsumer
    let hub: Hub
    let team: Team
    let team2: Team
    let fixedTime: DateTime

    const createIngestionConsumer = async (hub: Hub) => {
        const ingester = new IngestionConsumer(hub)
        // NOTE: We don't actually use kafka so we skip instantiation for faster tests
        ingester['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any
        await ingester.start()
        return ingester
    }

    const createEvent = (event?: Partial<PipelineEvent>): PipelineEvent => ({
        distinct_id: 'user-1',
        uuid: new UUIDT().toString(),
        token: team.api_token,
        ip: '127.0.0.1',
        site_url: 'us.posthog.com',
        now: fixedTime.toISO()!,
        event: '$pageview',
        ...event,
        properties: {
            $current_url: 'http://localhost:8000',
            ...(event?.properties || {}),
        },
    })

    const createCookielessEvent = (event?: Partial<PipelineEvent>): PipelineEvent => ({
        distinct_id: COOKIELESS_SENTINEL_VALUE,
        uuid: new UUIDT().toString(),
        token: team.api_token,
        ip: '127.0.0.1',
        site_url: 'us.posthog.com',
        now: fixedTime.toISO()!,
        event: '$pageview',
        ...event,
        properties: {
            $current_url: 'http://localhost:8000',
            $host: 'localhost:8000',
            $raw_user_agent: 'Chrome',
            $session_id: null,
            $device_id: null,
            [COOKIELESS_MODE_FLAG_PROPERTY]: true,
            ...(event?.properties || {}),
        },
    })

    beforeEach(async () => {
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        jest.spyOn(Date.prototype, 'toISOString').mockReturnValue(fixedTime.toISO()!)

        offsetIncrementer = 0
        await resetTestDatabase()
        hub = await createHub()

        // hub.kafkaProducer = mockProducer
        team = await getFirstTeam(hub)
        const team2Id = await createTeam(hub.db.postgres, team.organization_id)
        team2 = (await getTeam(hub, team2Id))!
    })

    afterEach(async () => {
        if (ingester) {
            await ingester.stop()
        }
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('general', () => {
        beforeEach(async () => {
            ingester = await createIngestionConsumer(hub)
        })

        it('should have the correct config', () => {
            expect(ingester['name']).toMatchInlineSnapshot(`"ingestion-consumer-events_plugin_ingestion_test"`)
            expect(ingester['groupId']).toMatchInlineSnapshot(`"events-ingestion-consumer"`)
            expect(ingester['topic']).toMatchInlineSnapshot(`"events_plugin_ingestion_test"`)
            expect(ingester['dlqTopic']).toMatchInlineSnapshot(`"events_plugin_ingestion_dlq_test"`)
            expect(ingester['overflowTopic']).toMatchInlineSnapshot(`"events_plugin_ingestion_overflow_test"`)
        })

        it('should process a standard event', async () => {
            await ingester.handleKafkaBatch(createKafkaMessages([createEvent()]))

            expect(forSnapshot(mockProducerObserver.getProducedKafkaMessages())).toMatchSnapshot()
        })

        it('should process a cookieless event', async () => {
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team SET cookieless_server_hash_mode = $1 WHERE id = $2`,
                [CookielessServerHashMode.Stateful, team.id],
                'set cookieless to stateful'
            )
            await ingester.handleKafkaBatch(createKafkaMessages([createCookielessEvent()]))

            expect(forSnapshot(mockProducerObserver.getProducedKafkaMessages())).toMatchSnapshot()
        })

        it('should drop a cookieless event if the team has cookieless disabled', async () => {
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team SET cookieless_server_hash_mode = $1 WHERE id = $2`,
                [CookielessServerHashMode.Disabled, team.id],
                'set cookieless to disabled'
            )
            await ingester.handleKafkaBatch(createKafkaMessages([createCookielessEvent()]))

            expect(mockProducerObserver.getProducedKafkaMessages()).toHaveLength(0)
        })

        it('should merge existing kafka_consumer_breadcrumbs in message header with new ones', async () => {
            const event = createEvent()
            const messages = createKafkaMessages([event])

            const existingBreadcrumb = {
                topic: 'previous-topic',
                offset: 123,
                partition: 0,
                processed_at: '2024-01-01T00:00:00.000Z',
                consumer_id: 'previous-consumer',
            }
            messages[0].headers = [
                {
                    'kafka-consumer-breadcrumbs': Buffer.from(JSON.stringify([existingBreadcrumb])),
                },
            ]
            await ingester.handleKafkaBatch(messages)

            const producedMessages =
                mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
            expect(producedMessages.length).toBe(1)

            const headers = producedMessages[0].headers || {}
            const breadcrumbHeader = headers['kafka-consumer-breadcrumbs']

            expect(breadcrumbHeader).toBeDefined()

            const parsedBreadcrumbs = parseJSON(breadcrumbHeader.toString())
            expect(Array.isArray(parsedBreadcrumbs)).toBe(true)
            expect(parsedBreadcrumbs.length).toBe(2)

            expect(parsedBreadcrumbs[0]).toMatchObject(existingBreadcrumb)

            expect(parsedBreadcrumbs[1]).toMatchObject({
                topic: 'test',
                offset: expect.any(Number),
                partition: expect.any(Number),
                processed_at: fixedTime.toISO()!,
                consumer_id: ingester['groupId'],
            })
        })

        it('should not blend person properties from 2 different cookieless users', async () => {
            const events = [
                createCookielessEvent({
                    ip: '1.2.3.4',
                    properties: {
                        $set: {
                            a: 'a',
                            ab: 'a',
                        },
                    },
                }),
                createCookielessEvent({
                    ip: '5.6.7.8', // different IP address means different user
                    properties: {
                        $set: {
                            b: 'b',
                            ab: 'b',
                        },
                    },
                }),
            ]
            const input = createKafkaMessages(events)
            await ingester.handleKafkaBatch(input)
            const messages = mockProducerObserver.getProducedKafkaMessages()
            const eventsA = messages.filter(
                (m) =>
                    m.topic === 'clickhouse_events_json_test' &&
                    m.value.person_properties &&
                    parseJSON(m.value.person_properties as any)?.a
            )
            const eventsB = messages.filter(
                (m) =>
                    m.topic === 'clickhouse_events_json_test' &&
                    m.value.person_properties &&
                    parseJSON(m.value.person_properties as any)?.b
            )
            expect(eventsA[0].value.person_id).not.toEqual(eventsB[0].value.person_id)
            expect(forSnapshot(eventsA)).toMatchSnapshot()
            expect(forSnapshot(eventsB)).toMatchSnapshot()
        })

        describe('overflow', () => {
            const now = () => DateTime.now().toMillis()
            beforeEach(() => {
                // Just to make it easy to see what is configured
                expect(hub.EVENT_OVERFLOW_BUCKET_CAPACITY).toEqual(1000)
            })

            it('should emit to overflow if token and distinct_id are overflowed', async () => {
                ingester['overflowRateLimiter'].consume(`${team.api_token}:overflow-distinct-id`, 1000, now())
                const overflowMessages = createKafkaMessages([createEvent({ distinct_id: 'overflow-distinct-id' })])
                await ingester.handleKafkaBatch(overflowMessages)
                expect(
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                ).toHaveLength(0)
                expect(
                    mockProducerObserver.getProducedKafkaMessagesForTopic('events_plugin_ingestion_overflow_test')
                ).toHaveLength(1)
                expect(
                    forSnapshot(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('events_plugin_ingestion_overflow_test')
                    )
                ).toMatchSnapshot()
            })

            it('does not overflow if it is consuming from the overflow topic', async () => {
                ingester['topic'] = 'events_plugin_ingestion_overflow_test'
                ingester['overflowRateLimiter'].consume(`${team.api_token}:overflow-distinct-id`, 1000, now())

                const overflowMessages = createKafkaMessages([createEvent({ distinct_id: 'overflow-distinct-id' })])
                await ingester.handleKafkaBatch(overflowMessages)

                expect(
                    mockProducerObserver.getProducedKafkaMessagesForTopic('events_plugin_ingestion_overflow_test')
                ).toHaveLength(0)
                expect(
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                ).toHaveLength(1)
            })

            describe('force overflow', () => {
                beforeEach(async () => {
                    // Reset ingester with force overflow token:distinct_id pair
                    await ingester.stop()
                    hub.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID = `${team.api_token}:team1-user`
                    ingester = await createIngestionConsumer(hub)
                })

                it('should force events with matching token:distinct_id to overflow', async () => {
                    const events = [
                        createEvent({ token: team.api_token, distinct_id: 'team1-user' }), // should overflow
                        createEvent({ token: team.api_token, distinct_id: 'team1-other' }), // should not overflow (different distinct_id)
                        createEvent({ token: team2.api_token, distinct_id: 'team1-user' }), // should not overflow (different token)
                    ]
                    const messages = createKafkaMessages(events)

                    await ingester.handleKafkaBatch(messages)

                    // Only the matching token:distinct_id event should be routed to overflow
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('events_plugin_ingestion_overflow_test')
                    ).toHaveLength(1)
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                    ).toHaveLength(2)

                    // Verify the right event went to overflow and the right events were processed normally
                    const overflowMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(
                        'events_plugin_ingestion_overflow_test'
                    )
                    const normalMessages =
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')

                    expect(overflowMessages[0].value.distinct_id).toEqual('team1-user')
                    expect(overflowMessages[0].value.token).toEqual(team.api_token)
                    expect(normalMessages.map((m) => m.value.distinct_id).sort()).toEqual(['team1-other', 'team1-user'])

                    // Add snapshot for the overflow messages
                    expect(forSnapshot(overflowMessages)).toMatchSnapshot('force overflow messages')
                })

                it('should handle multiple token:distinct_id pairs in force overflow setting', async () => {
                    // Reset ingester with multiple force overflow token:distinct_id pairs
                    await ingester.stop()
                    hub.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID = `${team.api_token}:user1,${team2.api_token}:user2`
                    ingester = await createIngestionConsumer(hub)

                    const events = [
                        createEvent({ token: team.api_token, distinct_id: 'user1' }), // should overflow
                        createEvent({ token: team.api_token, distinct_id: 'other' }), // should not overflow
                        createEvent({ token: team2.api_token, distinct_id: 'user2' }), // should overflow
                        createEvent({ token: team2.api_token, distinct_id: 'other' }), // should not overflow
                    ]
                    const messages = createKafkaMessages(events)

                    await ingester.handleKafkaBatch(messages)

                    // Both matching token:distinct_id pairs should be routed to overflow
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('events_plugin_ingestion_overflow_test')
                    ).toHaveLength(2)
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                    ).toHaveLength(2)

                    // Verify both matching events went to overflow
                    const overflowMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(
                        'events_plugin_ingestion_overflow_test'
                    )
                    const normalMessages =
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')

                    // Sort messages by distinct_id to make the test deterministic
                    const sortedOverflowMessages = [...overflowMessages].sort((a, b) =>
                        String(a.value.distinct_id).localeCompare(String(b.value.distinct_id))
                    )

                    expect(sortedOverflowMessages.map((m) => [m.value.token, m.value.distinct_id])).toEqual([
                        [team.api_token, 'user1'],
                        [team2.api_token, 'user2'],
                    ])
                    expect(normalMessages.map((m) => m.value.distinct_id).sort()).toEqual(['other', 'other'])

                    // Add snapshot for the overflow messages
                    expect(forSnapshot(sortedOverflowMessages)).toMatchSnapshot(
                        'force overflow messages multiple pairs'
                    )
                })
            })
        })
    })

    describe('dropping events', () => {
        describe.each(['headers', 'payload'] as const)('via %s', (kind) => {
            const addMessageHeaders = (message: Message, token?: string, distinctId?: string) => {
                if (kind !== 'headers') {
                    return
                }
                message.headers = []

                if (distinctId) {
                    message.headers.push({
                        key: 'distinct_id',
                        value: Buffer.from(distinctId),
                    })
                }
                if (token) {
                    message.headers.push({
                        key: 'token',
                        value: Buffer.from(token),
                    })
                }
            }

            beforeEach(() => {
                jest.spyOn(logger, 'debug')
            })

            const expectDropLogs = (pairs: [string, string | undefined][]) => {
                for (const [token, distinctId] of pairs) {
                    expect(jest.mocked(logger.debug)).toHaveBeenCalledWith('🔁', 'Dropped event', {
                        distinctId,
                        token,
                    })
                }
            }

            describe('with DROP_EVENTS_BY_TOKEN_DISTINCT_ID drops events with matching token:distinct_id when only event keys are listed', () => {
                beforeEach(async () => {
                    hub.DROP_EVENTS_BY_TOKEN_DISTINCT_ID = `${team.api_token}:distinct-id-to-ignore,phc_other:distinct-id-to-ignore`
                    ingester = await createIngestionConsumer(hub)
                })
                it('should drop events with matching token and distinct_id', async () => {
                    const messages = createKafkaMessages([
                        createEvent({
                            distinct_id: 'distinct-id-to-ignore',
                        }),
                    ])
                    addMessageHeaders(messages[0], team.api_token, 'distinct-id-to-ignore')
                    await ingester.handleKafkaBatch(messages)
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                    ).toHaveLength(0)
                    expectDropLogs([[team.api_token, 'distinct-id-to-ignore']])
                })

                it('should not drop events for a different team token', async () => {
                    const messages = createKafkaMessages([
                        createEvent({
                            token: team2.api_token,
                            distinct_id: 'distinct-id-to-ignore',
                        }),
                    ])
                    addMessageHeaders(messages[0], team2.api_token, 'distinct-id-to-ignore')
                    await ingester.handleKafkaBatch(messages)
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                    ).not.toHaveLength(0)
                    expectDropLogs([])
                })

                it('should not drop events for a different distinct_id', async () => {
                    const messages = createKafkaMessages([
                        createEvent({
                            distinct_id: 'other-id',
                        }),
                    ])
                    addMessageHeaders(messages[0], team.api_token, 'not-ignored')
                    await ingester.handleKafkaBatch(messages)
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                    ).not.toHaveLength(0)
                    expectDropLogs([])
                })
            })

            describe('with DROP_EVENTS_BY_TOKEN_DISTINCT_ID drops all team events when only token is listed', () => {
                beforeEach(async () => {
                    const distinct_id_to_drop = 'team1_user_to_drop'
                    hub.DROP_EVENTS_BY_TOKEN_DISTINCT_ID = `${team.api_token}:${distinct_id_to_drop},${team2.api_token}`
                    ingester = await createIngestionConsumer(hub)
                })

                it('should still drop events with matching token and distinct_id (event key)', async () => {
                    const distinct_id_to_drop = 'team1_user_to_drop'
                    const messages = createKafkaMessages([
                        createEvent({
                            distinct_id: distinct_id_to_drop,
                        }),
                    ])
                    addMessageHeaders(messages[0], team.api_token, distinct_id_to_drop)
                    await ingester.handleKafkaBatch(messages)
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                    ).toHaveLength(0)
                    expectDropLogs([[team.api_token, distinct_id_to_drop]])
                })

                it('should not drop all events for team with event key listed when distinct_id differs in event', async () => {
                    const unlisted_distinct_id = 'team1_user_NOT_to_drop'
                    const messages = createKafkaMessages([
                        createEvent({
                            token: team.api_token,
                            distinct_id: unlisted_distinct_id,
                        }),
                    ])
                    addMessageHeaders(messages[0], team.api_token, unlisted_distinct_id)
                    await ingester.handleKafkaBatch(messages)
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                    ).not.toHaveLength(0)
                    expectDropLogs([])
                })

                it('should drop all events for team with only token listed to be dropped', async () => {
                    const any_distinct_id = 'any_user'
                    const other_distinct_id = 'other_user'

                    const messages = createKafkaMessages([
                        createEvent({
                            token: team2.api_token,
                            distinct_id: any_distinct_id,
                        }),
                        createEvent({
                            token: team2.api_token,
                            distinct_id: other_distinct_id,
                        }),
                    ])
                    addMessageHeaders(messages[0], team2.api_token, any_distinct_id)
                    addMessageHeaders(messages[1], team2.api_token, other_distinct_id)

                    await ingester.handleKafkaBatch(messages)
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_events_json_test')
                    ).toHaveLength(0)
                    expectDropLogs([
                        [team2.api_token, any_distinct_id],
                        [team2.api_token, other_distinct_id],
                    ])
                })
            })
        })
    })

    describe('event batching', () => {
        beforeEach(async () => {
            ingester = await createIngestionConsumer(hub)
        })

        it('should batch events based on the distinct_id', () => {
            const messages = [
                ...createIncomingEventsWithTeam(
                    [
                        createEvent({ distinct_id: 'distinct-id-1' }),
                        createEvent({ distinct_id: 'distinct-id-1' }),
                        createEvent({ distinct_id: 'distinct-id-2' }),
                        createEvent({ distinct_id: 'distinct-id-1' }),
                    ],
                    team
                ),
                ...createIncomingEventsWithTeam(
                    [createEvent({ token: team2.api_token, distinct_id: 'distinct-id-1' })],
                    team2
                ),
            ]

            const batches = ingester['groupEventsByDistinctId'](messages)

            expect(Object.keys(batches)).toHaveLength(3)

            // Rewrite the test to check for the overall object with the correct length
            expect(batches).toEqual({
                [`${team.api_token}:distinct-id-1`]: {
                    distinctId: 'distinct-id-1',
                    token: team.api_token,
                    events: [expect.any(Object), expect.any(Object), expect.any(Object)],
                },
                [`${team.api_token}:distinct-id-2`]: {
                    distinctId: 'distinct-id-2',
                    token: team.api_token,
                    events: [expect.any(Object)],
                },
                [`${team2.api_token}:distinct-id-1`]: {
                    distinctId: 'distinct-id-1',
                    token: team2.api_token,
                    events: [expect.any(Object)],
                },
            })
        })
    })

    describe('error handling', () => {
        let messages: Message[]

        beforeEach(async () => {
            ingester = await createIngestionConsumer(hub)
            // Simulate some sort of error happening by mocking out the runner
            messages = createKafkaMessages([createEvent()])
            jest.spyOn(logger, 'error').mockImplementation(() => {})
        })

        afterEach(() => {})

        it('should handle explicitly non retriable errors by sending to DLQ', async () => {
            // NOTE: I don't think this makes a lot of sense but currently is just mimicing existing behavior for the migration
            // We should figure this out better and have more explictly named errors

            const error: any = new Error('test')
            error.isRetriable = false
            jest.spyOn(ingester as any, 'getEventPipelineRunnerV1').mockReturnValue({
                runEventPipeline: () => {
                    throw error
                },
            })

            await ingester.handleKafkaBatch(messages)

            expect(jest.mocked(logger.error)).toHaveBeenCalledWith('🔥', 'Error processing message', expect.any(Object))

            expect(forSnapshot(mockProducerObserver.getProducedKafkaMessages())).toMatchSnapshot()
        })

        it.each([undefined, true])('should throw if isRetriable is set to %s', async (isRetriable) => {
            const error: any = new Error('test')
            error.isRetriable = isRetriable
            jest.spyOn(ingester as any, 'getEventPipelineRunnerV1').mockReturnValue({
                runEventPipeline: () => {
                    throw error
                },
            })

            await expect(ingester.handleKafkaBatch(messages)).rejects.toThrow()
        })
    })

    describe('typical event processing', () => {
        /**
         * NOTE: The majority of these tests should be done in the event pipeline runner but
         * this is a good place to have some high level happy paths
         */

        beforeEach(async () => {
            ingester = await createIngestionConsumer(hub)
        })

        const eventTests: [string, () => PipelineEvent[]][] = [
            ['normal event', () => [createEvent()]],
            [
                '$identify event',
                () => [createEvent({ event: '$identify', properties: { $set: { $email: 'test@test.com' } } })],
            ],
            [
                'multiple events',
                () => [
                    createEvent({
                        event: '$pageview',
                        distinct_id: 'anonymous-id-1',
                        properties: { $current_url: 'https://example.com/page1' },
                    }),
                    createEvent({
                        event: '$identify',
                        distinct_id: 'identified-id-1',
                        properties: { $set: { $email: 'test@test.com' }, $anonymous_distinct_id: 'anonymous-id-1' },
                    }),
                    createEvent({
                        event: '$pageview',
                        distinct_id: 'identified-id-1',
                        properties: { $current_url: 'https://example.com/page2' },
                    }),
                ],
            ],
            // [
            //     'heatmap event',
            //     () => [
            //         createEvent({
            //             distinct_id: 'distinct-id-1',
            //             event: '$$heatmap',
            //             properties: {
            //                 $heatmap_data: {
            //                     'http://localhost:3000/': [
            //                         {
            //                             x: 1020,
            //                             y: 363,
            //                             target_fixed: false,
            //                             type: 'mousemove',
            //                         },
            //                         {
            //                             x: 634,
            //                             y: 460,
            //                             target_fixed: false,
            //                             type: 'click',
            //                         },
            //                     ],
            //                 },
            //             },
            //         }),
            //     ],
            // ],
            [
                // NOTE: This currently returns as is - for now we keep this broken but once we release the new ingester we should fix this
                'malformed person information',
                () => [
                    createEvent({
                        distinct_id: 'distinct-id-1',
                        properties: { $set: 'INVALID', $unset: [[[['definitel invalid']]]] },
                    }),
                ],
            ],
            ['malformed event', () => [createEvent({ event: '' })]],
            ['event with common distinct_id that gets dropped', () => [createEvent({ distinct_id: 'distinct_id' })]],
            [
                'ai event',
                () => [
                    createEvent({
                        event: '$ai_generation',
                        properties: {
                            $ai_model: 'gpt-4',
                            $ai_provider: 'openai',
                            $ai_input_tokens: 100,
                            $ai_output_tokens: 50,
                        },
                    }),
                ],
            ],
            [
                'person processing off',
                () => [createEvent({ event: '$pageview', properties: { $process_person_profile: false } })],
            ],
            [
                'forced person upgrade',
                () => [
                    createEvent({
                        event: '$pageview',
                        properties: { $process_person_profile: false, $set: { update1: '1' } },
                    }),
                    createEvent({
                        event: '$identify',
                        properties: { $process_person_profile: true, $set: { email: 'test@example.com' } },
                    }),
                    // Add an event at least a minute in the future and it should get force upgraded
                    createEvent({
                        event: '$pageview',
                        properties: { $process_person_profile: false, $set: { update2: '2' } },
                        timestamp: DateTime.now().plus({ minutes: 2 }).toISO(),
                    }),
                    // Add a person-full event and ensure all properties are there that should be
                    createEvent({
                        event: '$pageview',
                        properties: { $process_person_profile: true, $set: { update3: '3' } },
                        timestamp: DateTime.now().plus({ minutes: 3 }).toISO(),
                    }),
                    // Snapshot should contain update2 and update3 but not update1
                ],
            ],
            [
                'client ingestion warning',
                () => [
                    createEvent({
                        event: '$$client_ingestion_warning',
                        properties: { $$client_ingestion_warning_message: 'test' },
                    }),
                ],
            ],
            [
                'groups',
                () => [
                    createEvent({
                        event: '$pageview',
                        properties: {
                            $groups: {
                                a: 'group-a',
                                b: 'group-b',
                                c: 'group-c',
                                d: 'group-d',
                                e: 'group-e',
                                f: 'group-f',
                            },
                        },
                    }),
                    createEvent({
                        event: '$groupidentify',
                        properties: {
                            $group_type: 'a',
                            $group_key: 'group-a',
                            $group_set: {
                                id: 'group-a',
                                foo: 'bar',
                            },
                        },
                    }),
                    // This triggers an event but not a groups clickhouse change as the max groups is already hit
                    createEvent({
                        event: '$groupidentify',
                        properties: {
                            $group_type: 'f',
                            $group_key: 'group-f',
                            $group_set: {
                                id: 'group-f',
                                foo: 'bar',
                            },
                        },
                    }),
                ],
            ],
            [
                'person property merging via alias',
                () => {
                    const anonId1 = new UUIDT().toString()
                    const anonId2 = new UUIDT().toString()
                    return [
                        createEvent({
                            distinct_id: anonId1,
                            event: 'custom event',
                            properties: { $set: { k: 'v' } },
                        }),
                        createEvent({
                            distinct_id: anonId2,
                            event: 'custom event',
                            properties: { $set: { j: 'w' } },
                        }),
                        // final event should have k, j, l
                        createEvent({
                            distinct_id: anonId2,
                            event: '$create_alias',
                            properties: { alias: anonId1, $set: { l: 'x' } },
                        }),
                    ]
                },
            ],
        ]

        it.each(eventTests)('%s', async (_, createEvents) => {
            const messages = createKafkaMessages(createEvents())
            await ingester.handleKafkaBatch(messages)

            // Tricky due to some parallel processing race conditions order isn't deterministic
            // So we sort by specific properties to make it deterministic
            const sortingKey = (message: DecodedKafkaMessage) => {
                const value = message.value
                return `${value.topic}:${value.team_id}:${value.distinct_id}:${value.properties}`
            }

            const sortedMessages = mockProducerObserver
                .getProducedKafkaMessages()
                .sort((a, b) => sortingKey(a).localeCompare(sortingKey(b)))

            expect(forSnapshot(sortedMessages)).toMatchSnapshot()
        })
    })

    describe('transformations', () => {
        let transformationFunction: HogFunctionType
        const TRANSFORMATION_TEST_TIMEOUT = 30000

        beforeAll(() => {
            jest.setTimeout(TRANSFORMATION_TEST_TIMEOUT)
        })

        afterAll(() => {
            jest.setTimeout(DEFAULT_TEST_TIMEOUT)
        })

        const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
            const { hog, bytecode, name } = hogFunction
            const item = await _insertHogFunction(hub.postgres, team.id, {
                hog,
                bytecode,
                name: name || 'Test Function',
                type: 'transformation',
            })
            return item
        }

        beforeEach(async () => {
            // Create a transformation function using the geoip template as an example
            const hogByteCode = await compileHog(geoipTemplate.hog)
            transformationFunction = await insertHogFunction({
                name: 'GeoIP Transformation',
                hog: geoipTemplate.hog,
                bytecode: hogByteCode,
            })

            ingester = await createIngestionConsumer(hub)
        })

        it(
            'should call hogwatcher state caching methods and observe results when hogwatcher is enabled (sample rate = 1)',
            async () => {
                // Set hogwatcher enabled (100% sample rate)
                hub.CDP_HOG_WATCHER_SAMPLE_RATE = 1

                // Create spies for methods after the service is configured
                const fetchAndCacheSpy = jest.spyOn(ingester.hogTransformer, 'fetchAndCacheHogFunctionStates')
                const clearStatesSpy = jest.spyOn(ingester.hogTransformer, 'clearHogFunctionStates')
                const observeResultsSpy = jest.spyOn(ingester.hogTransformer['hogWatcher'], 'observeResults')

                // Process batch with hogwatcher enabled
                // in this stage we do not have the teamId on the event but the token is present
                const event = createEvent({
                    ip: '89.160.20.129',
                    properties: { $ip: '89.160.20.129' },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                // Verify that fetchAndCacheHogFunctionStates and clearHogFunctionStates were called
                expect(fetchAndCacheSpy).toHaveBeenCalled()
                expect(clearStatesSpy).toHaveBeenCalled()

                // Verify the full integration flow worked
                expect(observeResultsSpy).toHaveBeenCalled()

                // Verify that results were passed to observeResults with the correct structure
                const results = observeResultsSpy.mock.calls[0][0]
                expect(results).toBeInstanceOf(Array)
                expect(results.length).toBeGreaterThan(0)

                // Check that the results contain our transformation function
                const functionResult = results.find((r) => r.invocation.functionId === transformationFunction.id)
                expect(functionResult).toBeDefined()
                expect(functionResult?.finished).toBe(true)
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'should not call hogwatcher state caching methods when hogwatcher is disabled (sample rate = 0)',
            async () => {
                // Set hogwatcher disabled (0% sample rate)
                hub.CDP_HOG_WATCHER_SAMPLE_RATE = 0

                // Create spies for methods after the service is configured
                const fetchAndCacheSpy = jest.spyOn(ingester.hogTransformer, 'fetchAndCacheHogFunctionStates')
                const clearStatesSpy = jest.spyOn(ingester.hogTransformer, 'clearHogFunctionStates')

                // Process batch with hogwatcher disabled
                const event = createEvent({
                    ip: '89.160.20.129',
                    properties: { $ip: '89.160.20.129' },
                })
                const messages = createKafkaMessages([event])

                await ingester.handleKafkaBatch(messages)

                // Verify that fetchAndCacheHogFunctionStates and clearHogFunctionStates were NOT called
                expect(fetchAndCacheSpy).not.toHaveBeenCalled()
                expect(clearStatesSpy).not.toHaveBeenCalled()
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'should invoke transformation for matching team with error case',
            async () => {
                // make the geoip lookup fail
                const event = createEvent({
                    ip: '256.256.256.256',
                    properties: { $ip: '256.256.256.256' },
                })
                const messages = createKafkaMessages([event])

                const result = await ingester.handleKafkaBatch(messages)
                await result.backgroundTask

                // Verify metrics were published
                const metricsMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')
                expect(metricsMessages).toEqual([
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: transformationFunction.id,
                            count: 1,
                            metric_kind: 'success',
                            metric_name: 'succeeded',
                            team_id: team.id,
                            timestamp: '2025-01-01 00:00:00.000',
                        },
                    },
                ])

                // Verify log entries were published
                const logMessages = mockProducerObserver.getProducedKafkaMessagesForTopic('log_entries_test')
                expect(logMessages).toEqual([
                    {
                        key: expect.any(String),
                        topic: 'log_entries_test',
                        value: {
                            instance_id: expect.any(String),
                            level: 'info',
                            log_source: 'hog_function',
                            log_source_id: transformationFunction.id,
                            message: 'geoip lookup failed for ip, 256.256.256.256',
                            team_id: team.id,
                            timestamp: expect.stringMatching(/2025-01-01 00:00:00\.\d{3}/),
                        },
                    },
                    {
                        key: expect.any(String),
                        topic: 'log_entries_test',
                        value: {
                            instance_id: expect.any(String),
                            level: 'debug',
                            log_source: 'hog_function',
                            log_source_id: transformationFunction.id,
                            message: expect.stringMatching(
                                /^Function completed in \d+\.?\d*ms\. Sync: \d+ms\. Mem: \d+ bytes\. Ops: \d+\. Event: '\S+'$/
                            ),
                            team_id: team.id,
                            timestamp: expect.stringMatching(/2025-01-01 00:00:00\.\d{3}/),
                        },
                    },
                ])
            },
            TRANSFORMATION_TEST_TIMEOUT
        )

        it(
            'should invoke transformation for matching team with success case',
            async () => {
                const event = createEvent({
                    ip: '89.160.20.129',
                    properties: { $ip: '89.160.20.129' },
                })
                const messages = createKafkaMessages([event])

                const result = await ingester.handleKafkaBatch(messages)
                await result.backgroundTask

                // Verify metrics were published
                const metricsMessages =
                    mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')
                expect(metricsMessages).toEqual([
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: transformationFunction.id,
                            count: 1,
                            metric_kind: 'success',
                            metric_name: 'succeeded',
                            team_id: team.id,
                            timestamp: '2025-01-01 00:00:00.000',
                        },
                    },
                ])

                // Verify log entries were published
                const logMessages = mockProducerObserver.getProducedKafkaMessagesForTopic('log_entries_test')
                expect(logMessages).toEqual([
                    {
                        key: expect.any(String),
                        topic: 'log_entries_test',
                        value: {
                            instance_id: expect.any(String),
                            level: 'info',
                            log_source: 'hog_function',
                            log_source_id: transformationFunction.id,
                            message: expect.stringContaining('geoip location data for ip:'),
                            team_id: team.id,
                            timestamp: expect.stringMatching(/2025-01-01 00:00:00\.\d{3}/),
                        },
                    },
                    {
                        key: expect.any(String),
                        topic: 'log_entries_test',
                        value: {
                            instance_id: expect.any(String),
                            level: 'debug',
                            log_source: 'hog_function',
                            log_source_id: transformationFunction.id,
                            message: expect.stringMatching(
                                /^Function completed in \d+\.?\d*ms\. Sync: \d+ms\. Mem: \d+ bytes\. Ops: \d+\. Event: '\S+'$/
                            ),
                            team_id: team.id,
                            timestamp: expect.stringMatching(/2025-01-01 00:00:00\.\d{3}/),
                        },
                    },
                ])
            },
            TRANSFORMATION_TEST_TIMEOUT
        )
    })

    describe('testing topic', () => {
        it('should emit to the testing topic', async () => {
            hub.INGESTION_CONSUMER_TESTING_TOPIC = 'testing_topic'
            ingester = await createIngestionConsumer(hub)

            const messages = createKafkaMessages([createEvent()])
            await ingester.handleKafkaBatch(messages)

            expect(forSnapshot(mockProducerObserver.getProducedKafkaMessages())).toMatchInlineSnapshot(`
                [
                  {
                    "headers": {},
                    "key": "THIS IS NOT A TOKEN FOR TEAM 2:user-1",
                    "topic": "testing_topic",
                    "value": {
                      "data": "{"distinct_id":"user-1","uuid":"<REPLACED-UUID-0>","token":"THIS IS NOT A TOKEN FOR TEAM 2","ip":"127.0.0.1","site_url":"us.posthog.com","now":"2025-01-01T00:00:00.000Z","event":"$pageview","properties":{"$current_url":"http://localhost:8000"}}",
                      "distinct_id": "user-1",
                      "ip": "127.0.0.1",
                      "now": "2025-01-01T00:00:00.000Z",
                      "token": "THIS IS NOT A TOKEN FOR TEAM 2",
                      "uuid": "<REPLACED-UUID-0>",
                    },
                  },
                ]
            `)
        })
    })
})
