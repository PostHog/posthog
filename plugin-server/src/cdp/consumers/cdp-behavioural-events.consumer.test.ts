import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { resetKafka } from '~/tests/helpers/kafka'

import { buildInlineFiltersForCohorts, createCohort, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS } from '../../config/kafka-topics'
import { Hub, RawClickHouseEvent, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { CdpBehaviouralEventsConsumer } from './cdp-behavioural-events.consumer'

jest.setTimeout(20_000)

const TEST_FILTERS = {
    // Simple pageview event filter: event == '$pageview'
    pageview: ['_H', 1, 32, '$pageview', 32, 'event', 1, 1, 11],

    // Chrome browser AND pageview event filter: properties.$browser == 'Chrome' AND event == '$pageview'
    chromePageview: [
        '_H',
        1,
        32,
        'Chrome',
        32,
        '$browser',
        32,
        'properties',
        1,
        2,
        11,
        32,
        '$pageview',
        32,
        'event',
        1,
        1,
        11,
        3,
        2,
        4,
        1,
    ],

    // Complex filter: pageview event AND (Chrome browser contains match OR has IP property)
    complexChromeWithIp: [
        '_H',
        1,
        32,
        '$pageview',
        32,
        'event',
        1,
        1,
        11,
        32,
        '%Chrome%',
        32,
        '$browser',
        32,
        'properties',
        1,
        2,
        2,
        'toString',
        1,
        18,
        3,
        2,
        32,
        '$pageview',
        32,
        'event',
        1,
        1,
        11,
        31,
        32,
        '$ip',
        32,
        'properties',
        1,
        2,
        12,
        3,
        2,
        4,
        2,
    ],

    // Billing product activated filter
    billingProductActivated: [
        '_H',
        1,
        32,
        'billing product activated',
        32,
        'event',
        1,
        1,
        11,
        32,
        'platform_and_support',
        32,
        'product_key',
        32,
        'properties',
        1,
        2,
        11,
        32,
        'teams-20240208',
        32,
        'plans__platform_and_support',
        32,
        'properties',
        1,
        2,
        11,
        3,
        2,
        3,
        2,
    ],

    // Product unsubscribed filter
    productUnsubscribed: [
        '_H',
        1,
        32,
        'product unsubscribed',
        32,
        'event',
        1,
        1,
        11,
        32,
        'platform_and_support',
        32,
        'product',
        32,
        'properties',
        1,
        2,
        11,
        3,
        2,
    ],

    // Person property is_organization_first_user filter
    isOrgFirstUser: ['_H', 1, 29, 32, 'is_organization_first_user', 32, 'properties', 32, 'person', 1, 3, 11],
}

describe('CdpBehaviouralEventsConsumer', () => {
    let processor: CdpBehaviouralEventsConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetKafka()
        await resetTestDatabase()

        mockProducerObserver.resetKafkaProducer()
        hub = await createHub()
        team = await getFirstTeam(hub)

        processor = new CdpBehaviouralEventsConsumer(hub)
        await processor.start()
    })

    afterEach(async () => {
        await processor.stop()
        await closeHub(hub)
        jest.restoreAllMocks()
    })

    describe('cohort filter matching and Kafka publishing', () => {
        it('should publish pre-calculated events to Kafka when cohort filter matches', async () => {
            // Create a cohort with complex behavioral filter: pageview with browser event filter
            const conditionHash = 'test_hash_001'
            const filters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$pageview',
                                    type: 'behavioral',
                                    value: 'performed_event_multiple',
                                    bytecode: TEST_FILTERS.chromePageview,
                                    negation: false,
                                    operator: 'gte',
                                    event_type: 'events',
                                    conditionHash: conditionHash,
                                    event_filters: [
                                        { key: '$browser', type: 'event', value: 'Chrome', operator: 'exact' },
                                    ],
                                    operator_value: 5,
                                    explicit_datetime: '-30d',
                                },
                            ],
                        },
                    ],
                },
            })
            await createCohort(hub.postgres, team.id, 'Test cohort', filters)

            // Create a matching event
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const distinctId = 'test-distinct-123'
            const eventUuid = 'test-uuid-1'
            const timestamp = '2025-03-03T10:15:46.319000-08:00'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: '$pageview',
                            person_id: personId,
                            distinct_id: distinctId,
                            properties: JSON.stringify({ $browser: 'Chrome' }),
                            timestamp,
                            uuid: eventUuid,
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            // Parse messages which should create pre-calculated events
            const events = await processor._parseKafkaBatch(messages)

            // Should create one pre-calculated event for the matching cohort filter
            expect(events).toHaveLength(1)

            const preCalculatedEvent = events[0]
            expect(preCalculatedEvent.key).toBe(distinctId) // Partitioned by distinct_id

            expect(preCalculatedEvent.payload).toMatchObject({
                uuid: eventUuid,
                team_id: team.id,
                evaluation_timestamp: '2025-03-03 18:15:46.319',
                person_id: personId,
                distinct_id: distinctId,
                condition: conditionHash,
                source: `cohort_filter_${conditionHash}`,
            })
            // Test publishing the events to Kafka
            await processor['publishEvents'](events)

            // Check published messages to Kafka
            const kafkaMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(
                KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS
            )
            expect(kafkaMessages).toHaveLength(1)

            const publishedMessage = kafkaMessages[0]
            expect(publishedMessage.key).toBe(distinctId)
            expect(publishedMessage.value).toEqual(preCalculatedEvent.payload)
        })

        it('should not publish to Kafka when cohort filter does not match', async () => {
            // Create a cohort with Chrome + pageview filter
            const conditionHash = 'test_hash_002'
            const filters = buildInlineFiltersForCohorts({
                bytecode: TEST_FILTERS.chromePageview,
                conditionHash,
                type: 'behavioral',
                key: '$pageview',
            })
            await createCohort(hub.postgres, team.id, 'Test cohort', filters)

            // Create a non-matching event (Firefox instead of Chrome)
            const personId = '550e8400-e29b-41d4-a716-446655440000'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: '$pageview',
                            person_id: personId,
                            distinct_id: 'test-distinct-456',
                            properties: JSON.stringify({ $browser: 'Firefox' }), // Different browser
                            timestamp: '2025-03-03T10:15:46.319000-08:00',
                            uuid: 'test-uuid-2',
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            // Parse messages
            const events = await processor._parseKafkaBatch(messages)

            // Should not create any events since cohort filter doesn't match
            expect(events).toHaveLength(0)

            // Verify nothing was published to Kafka
            await processor['publishEvents'](events)
            const kafkaMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(
                KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS
            )
            expect(kafkaMessages).toHaveLength(0)
        })

        it('should deduplicate filters with same conditionHash for a team', async () => {
            // Create two cohorts with the same filter (same conditionHash)
            const conditionHash = 'dedup_test_hash_001'
            const filters = buildInlineFiltersForCohorts({ bytecode: TEST_FILTERS.pageview, conditionHash })

            // Create first cohort
            await createCohort(hub.postgres, team.id, 'First cohort', filters)
            // Create second cohort with same filter
            await createCohort(hub.postgres, team.id, 'Second cohort', filters)

            // Create a matching event
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const distinctId = 'test-distinct-dedup'
            const eventUuid = 'test-uuid-dedup'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: '$pageview',
                            person_id: personId,
                            distinct_id: distinctId,
                            properties: JSON.stringify({}),
                            timestamp: '2025-03-03T10:15:46.319000-08:00',
                            uuid: eventUuid,
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            // Parse messages
            const events = await processor._parseKafkaBatch(messages)

            // Should only create one event despite having two cohorts with same conditionHash
            expect(events).toHaveLength(1)

            const preCalculatedEvent = events[0]
            expect(preCalculatedEvent.payload.condition).toBe(conditionHash)
            expect(preCalculatedEvent.payload.source).toBe(`cohort_filter_${conditionHash}`)
        })

        it('should emit separate events for different cohorts with different conditionHashes', async () => {
            // Create two cohorts with different complex filters
            const conditionHash1 = 'multi_cohort_hash_001'
            const conditionHash2 = 'multi_cohort_hash_002'

            // First cohort: simple pageview behavioral filter
            const filters1 = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'OR',
                            values: [
                                {
                                    key: '$pageview',
                                    type: 'behavioral',
                                    value: 'performed_event',
                                    bytecode: TEST_FILTERS.pageview,
                                    negation: false,
                                    event_type: 'events',
                                    conditionHash: conditionHash1,
                                    explicit_datetime: '-30d',
                                },
                            ],
                        },
                    ],
                },
            })

            // Second cohort: complex behavioral filter with event_filters (AND structure)
            const filters2 = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$pageview',
                                    type: 'behavioral',
                                    value: 'performed_event_multiple',
                                    bytecode: TEST_FILTERS.chromePageview,
                                    negation: false,
                                    operator: 'gte',
                                    event_type: 'events',
                                    conditionHash: conditionHash2,
                                    event_filters: [
                                        { key: '$browser', type: 'event', value: 'Chrome', operator: 'exact' },
                                    ],
                                    operator_value: 5,
                                    explicit_datetime: '-30d',
                                },
                            ],
                        },
                    ],
                },
            })

            // Create first cohort (pageview only)
            await createCohort(hub.postgres, team.id, 'Pageview cohort', filters1)
            // Create second cohort (Chrome + pageview with event filters)
            await createCohort(hub.postgres, team.id, 'Chrome pageview cohort', filters2)

            // Create an event that matches both filters
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const distinctId = 'test-distinct-multi'
            const eventUuid = 'test-uuid-multi'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: '$pageview',
                            person_id: personId,
                            distinct_id: distinctId,
                            properties: JSON.stringify({ $browser: 'Chrome' }),
                            timestamp: '2025-03-03T10:15:46.319000-08:00',
                            uuid: eventUuid,
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            // Parse messages
            const events = await processor._parseKafkaBatch(messages)

            // Should create two events - one for each matching cohort filter
            expect(events).toHaveLength(2)

            // Sort by condition hash for consistent testing
            events.sort((a, b) => a.payload.condition.localeCompare(b.payload.condition))

            const [event1, event2] = events

            // First event should be for pageview filter
            expect(event1.payload.condition).toBe(conditionHash1)
            expect(event1.payload.source).toBe(`cohort_filter_${conditionHash1}`)
            expect(event1.key).toBe(distinctId)

            // Second event should be for Chrome + pageview filter
            expect(event2.payload.condition).toBe(conditionHash2)
            expect(event2.payload.source).toBe(`cohort_filter_${conditionHash2}`)
            expect(event2.key).toBe(distinctId)
        })

        it('should handle complex billing cohort filter with OR/AND structure', async () => {
            const filters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: 'billing product activated',
                                    type: 'behavioral',
                                    value: 'performed_event',
                                    bytecode: TEST_FILTERS.billingProductActivated,
                                    negation: false,
                                    event_type: 'events',
                                    conditionHash: '2946b8444e88565c',
                                    event_filters: [
                                        {
                                            key: 'product_key',
                                            type: 'event',
                                            value: ['platform_and_support'],
                                            operator: 'exact',
                                        },
                                        {
                                            key: 'plans__platform_and_support',
                                            type: 'event',
                                            value: ['teams-20240208'],
                                            operator: 'exact',
                                        },
                                    ],
                                    explicit_datetime: '-30d',
                                },
                                {
                                    key: 'product unsubscribed',
                                    type: 'behavioral',
                                    value: 'performed_event',
                                    bytecode: TEST_FILTERS.productUnsubscribed,
                                    negation: true,
                                    event_type: 'events',
                                    conditionHash: '4c6bb89ec315ba80',
                                    event_filters: [
                                        {
                                            key: 'product',
                                            type: 'event',
                                            value: ['platform_and_support'],
                                            operator: 'exact',
                                        },
                                    ],
                                    explicit_datetime: '-30d',
                                },
                                {
                                    key: 'is_organization_first_user',
                                    type: 'person',
                                    value: ['true'],
                                    bytecode: TEST_FILTERS.isOrgFirstUser,
                                    negation: false,
                                    operator: 'exact',
                                    conditionHash: '7937ba56a3e6348a',
                                },
                            ],
                        },
                    ],
                },
            })

            await createCohort(hub.postgres, team.id, 'Billing Product Cohort', filters)

            // Test 1: Event that matches billing product activated filter
            const personId1 = '950e8400-e29b-41d4-a716-446655440001'
            const distinctId1 = 'billing-cohort-test-1'
            const eventUuid1 = 'billing-cohort-uuid-1'
            const timestamp1 = '2025-03-03T17:00:00.000000-08:00'

            const messages1 = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: 'billing product activated',
                            person_id: personId1,
                            distinct_id: distinctId1,
                            properties: JSON.stringify({
                                product_key: 'platform_and_support',
                                plans__platform_and_support: 'teams-20240208',
                            }),
                            timestamp: timestamp1,
                            uuid: eventUuid1,
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            const events1 = await processor._parseKafkaBatch(messages1)

            expect(events1).toHaveLength(1)

            const preCalculatedEvent1 = events1[0]
            expect(preCalculatedEvent1.key).toBe(distinctId1)
            expect(preCalculatedEvent1.payload).toMatchObject({
                uuid: eventUuid1,
                team_id: team.id,
                person_id: personId1,
                distinct_id: distinctId1,
                condition: '2946b8444e88565c',
                source: 'cohort_filter_2946b8444e88565c',
            })
        })

        it('should not process person property filters as they are filtered out', async () => {
            // Create a cohort with person property filter
            const filters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: 'is_organization_first_user',
                                    type: 'person', // This type is filtered out
                                    value: ['true'],
                                    bytecode: TEST_FILTERS.isOrgFirstUser,
                                    negation: false,
                                    operator: 'exact',
                                    conditionHash: 'person_prop_test_001',
                                },
                            ],
                        },
                    ],
                },
            })

            await createCohort(hub.postgres, team.id, 'First Org User Cohort', filters)

            const personId = '850e8400-e29b-41d4-a716-446655440002'
            const distinctId = 'person-cohort-test-1'
            const eventUuid = 'person-cohort-uuid-1'
            const timestamp = '2025-03-03T18:00:00.000000-08:00'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: 'any event',
                            person_id: personId,
                            distinct_id: distinctId,
                            properties: JSON.stringify({}),
                            person_properties: JSON.stringify({
                                is_organization_first_user: 'true',
                            }),
                            timestamp,
                            uuid: eventUuid,
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            const events = await processor._parseKafkaBatch(messages)

            // Should NOT create any events since person filters are filtered out
            expect(events).toHaveLength(0)
        })

        it('should produce events for negated filters', async () => {
            // negated events will produce matching events
            const filters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: 'product unsubscribed',
                                    type: 'behavioral',
                                    value: 'performed_event',
                                    bytecode: TEST_FILTERS.productUnsubscribed,
                                    negation: true, // Negation flag is stored but not processed by consumer
                                    event_type: 'events',
                                    conditionHash: 'negated_unsub_test',
                                    event_filters: [
                                        {
                                            key: 'product',
                                            type: 'event',
                                            value: ['platform_and_support'],
                                            operator: 'exact',
                                        },
                                    ],
                                    explicit_datetime: '-30d',
                                },
                            ],
                        },
                    ],
                },
            })

            await createCohort(hub.postgres, team.id, 'Not Unsubscribed Cohort', filters)

            const personId = '750e8400-e29b-41d4-a716-446655440003'
            const distinctId = 'negation-test-1'
            const eventUuid = 'negation-uuid-1'
            const timestamp = '2025-03-03T19:00:00.000000-08:00'

            // Send a product unsubscribed event
            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: 'product unsubscribed',
                            person_id: personId,
                            distinct_id: distinctId,
                            properties: JSON.stringify({
                                product: 'platform_and_support',
                            }),
                            timestamp,
                            uuid: eventUuid,
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            const events = await processor._parseKafkaBatch(messages)

            // Should create an event because consumer doesn't handle negation
            // It just evaluates the bytecode which will return true for matching event
            expect(events).toHaveLength(1)

            const preCalculatedEvent = events[0]
            expect(preCalculatedEvent.key).toBe(distinctId)
            expect(preCalculatedEvent.payload).toMatchObject({
                uuid: eventUuid,
                team_id: team.id,
                person_id: personId,
                distinct_id: distinctId,
                condition: 'negated_unsub_test',
                source: 'cohort_filter_negated_unsub_test',
            })
        })
    })
})
