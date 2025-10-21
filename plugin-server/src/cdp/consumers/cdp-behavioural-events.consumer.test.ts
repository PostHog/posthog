import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { resetKafka } from '~/tests/helpers/kafka'

import { createAction, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
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

    describe('action matching and Kafka publishing', () => {
        it('should publish pre-calculated events to Kafka when action matches', async () => {
            // Create an action with Chrome + pageview filter
            const actionId = await createAction(hub.postgres, team.id, 'Test action', TEST_FILTERS.chromePageview)

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

            // Should create one pre-calculated event for the matching action
            expect(events).toHaveLength(1)

            const preCalculatedEvent = events[0]
            expect(preCalculatedEvent.key).toBe(distinctId) // Partitioned by distinct_id

            expect(preCalculatedEvent.payload).toMatchObject({
                uuid: eventUuid,
                team_id: team.id,
                evaluation_timestamp: '2025-03-03 18:15:46.319',
                person_id: personId,
                distinct_id: distinctId,
                condition: String(actionId),
                source: `action_${actionId}`,
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

        it('should not publish to Kafka when action does not match', async () => {
            // Create an action with Chrome + pageview filter
            await createAction(hub.postgres, team.id, 'Test action', TEST_FILTERS.chromePageview)

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

            // Should not create any events since action doesn't match
            expect(events).toHaveLength(0)

            // Verify nothing was published to Kafka
            await processor['publishEvents'](events)
            const kafkaMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(
                KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS
            )
            expect(kafkaMessages).toHaveLength(0)
        })
    })
})
