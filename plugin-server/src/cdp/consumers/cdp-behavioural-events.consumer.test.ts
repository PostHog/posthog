import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { resetKafka } from '~/tests/helpers/kafka'

import { createCohort, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
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
}

// Helper function to create compiled_bytecode array from bytecode
const createCompiledBytecode = (
    bytecode: any[],
    conditionHash: string,
    filterPath: string = 'properties.values[0]'
) => {
    return [
        {
            filter_path: filterPath,
            bytecode: bytecode,
            conditionHash: conditionHash,
        },
    ]
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
            // Create a cohort with Chrome + pageview filter
            const conditionHash = 'test_hash_001'
            const compiledBytecode = createCompiledBytecode(TEST_FILTERS.chromePageview, conditionHash)
            await createCohort(hub.postgres, team.id, 'Test cohort', compiledBytecode)

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
            const compiledBytecode = createCompiledBytecode(TEST_FILTERS.chromePageview, conditionHash)
            await createCohort(hub.postgres, team.id, 'Test cohort', compiledBytecode)

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
            const compiledBytecode = createCompiledBytecode(TEST_FILTERS.pageview, conditionHash)

            // Create first cohort
            await createCohort(hub.postgres, team.id, 'First cohort', compiledBytecode)
            // Create second cohort with same filter
            await createCohort(hub.postgres, team.id, 'Second cohort', compiledBytecode)

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
            // Create two cohorts with different filters
            const conditionHash1 = 'multi_cohort_hash_001'
            const conditionHash2 = 'multi_cohort_hash_002'

            const compiledBytecode1 = createCompiledBytecode(TEST_FILTERS.pageview, conditionHash1)
            const compiledBytecode2 = createCompiledBytecode(TEST_FILTERS.chromePageview, conditionHash2)

            // Create first cohort (pageview only)
            await createCohort(hub.postgres, team.id, 'Pageview cohort', compiledBytecode1)
            // Create second cohort (Chrome + pageview)
            await createCohort(hub.postgres, team.id, 'Chrome pageview cohort', compiledBytecode2)

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
    })
})
