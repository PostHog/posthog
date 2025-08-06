// eslint-disable-next-line simple-import-sort/imports
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { createHash } from 'crypto'

import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { KAFKA_CDP_PERSON_PERFORMED_EVENT } from '../../config/kafka-topics'
import { Hub, RawClickHouseEvent, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { CdpBehaviouralEventsConsumer, ProducedEvent } from './cdp-behavioural-events.consumer'
import { resetKafka } from '~/tests/helpers/kafka'
class TestableCdpBehaviouralEventsConsumer extends CdpBehaviouralEventsConsumer {
    public async testPublishEvents(events: ProducedEvent[]) {
        return this.publishEvents(events)
    }
}

jest.setTimeout(20_000)

describe('CdpBehaviouralEventsConsumer', () => {
    describe('Event Processing and Publishing', () => {
        let processor: TestableCdpBehaviouralEventsConsumer
        let hub: Hub
        let team: Team

        beforeEach(async () => {
            await resetKafka()
            await resetTestDatabase()

            hub = await createHub()
            team = await getFirstTeam(hub)

            processor = new TestableCdpBehaviouralEventsConsumer(hub)
            await processor.start()
        })

        afterEach(async () => {
            await processor.stop()
            await closeHub(hub)
        })

        it('should create both person-performed-event and behavioural-filter-match-event during message parsing', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const eventName = '$pageview'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: eventName,
                            person_id: personId,
                            properties: '{"$browser": "Chrome"}',
                            timestamp: '2023-01-01T00:00:00Z',
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            // Parse messages which should create both event types
            const events = await processor._parseKafkaBatch(messages)

            // Check that both events were created
            expect(events).toHaveLength(2)

            // Check person-performed-event
            const personEvent = events.find((e) => e.payload.type === 'person-performed-event')
            expect(personEvent).toBeDefined()
            expect(personEvent?.key).toBe(`${team.id}:${personId}:${eventName}`)
            expect(personEvent?.payload).toEqual({
                type: 'person-performed-event',
                personId,
                eventName,
                teamId: team.id,
            })

            // Check behavioural-filter-match-event
            const filterEvent = events.find((e) => e.payload.type === 'behavioural-filter-match-event')
            expect(filterEvent?.payload.type).toBe('behavioural-filter-match-event')
            expect(filterEvent?.payload.teamId).toBe(team.id)
            expect(filterEvent?.payload.personId).toBe(personId)
        })

        it('should use correct partition keys for both event types', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const eventName = '$pageview'
            const timestamp = '2023-01-01T00:00:00Z'
            const expectedDate = '2023-01-01'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: eventName,
                            person_id: personId,
                            timestamp,
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            const events = await processor._parseKafkaBatch(messages)

            // Check person-performed-event partition key: teamId:personId:eventName
            const personEvent = events.find((e) => e.payload.type === 'person-performed-event')
            expect(personEvent?.key).toBe(`${team.id}:${personId}:${eventName}`)

            // Check behavioural-filter-match-event partition key: teamId:personId:filterHash:date
            const filterEvent = events.find((e) => e.payload.type === 'behavioural-filter-match-event')
            const expectedFilterHash = createHash('sha256').update(eventName).digest('hex')
            expect(filterEvent?.key).toBe(`${team.id}:${personId}:${expectedFilterHash}:${expectedDate}`)
        })

        it('should handle missing person_id by throwing error', async () => {
            const eventName = '$pageview'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: eventName,
                            // Missing person_id
                            timestamp: '2023-01-01T00:00:00Z',
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            // Should not throw but should log error and not create events
            const events = await processor._parseKafkaBatch(messages)

            // No events should be created when person_id is missing
            expect(events).toHaveLength(0)
        })
    })

    describe('Event Publishing to Kafka', () => {
        let processor: TestableCdpBehaviouralEventsConsumer
        let hub: Hub
        let team: Team

        beforeEach(async () => {
            await resetKafka()
            await resetTestDatabase()

            hub = await createHub()
            team = await getFirstTeam(hub)

            processor = new TestableCdpBehaviouralEventsConsumer(hub)
            await processor.start()
        })

        afterEach(async () => {
            await processor.stop()
            await closeHub(hub)
        })

        it('should publish both event types to Kafka', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const eventName = '$pageview'

            // Add events to the queue manually
            const personEvent: ProducedEvent = {
                key: `${team.id}:${personId}:${eventName}`,
                payload: {
                    type: 'person-performed-event',
                    personId,
                    eventName,
                    teamId: team.id,
                },
            }

            const filterHash = createHash('sha256').update(eventName).digest('hex')
            const date = '2023-01-01'
            const filterEvent: ProducedEvent = {
                key: `${team.id}:${personId}:${filterHash}:${date}`,
                payload: {
                    type: 'behavioural-filter-match-event',
                    teamId: team.id,
                    personId,
                    filterHash,
                    date,
                },
            }

            // Publish the events
            await processor.testPublishEvents([personEvent, filterEvent])

            // Check published messages
            const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_CDP_PERSON_PERFORMED_EVENT)
            expect(messages).toHaveLength(2)

            // Check person-performed-event
            const personMessage = messages.find(
                (m) => (m.value as ProducedEvent).payload.type === 'person-performed-event'
            )
            expect(personMessage?.key).toBe(`${team.id}:${personId}:${eventName}`)
            expect(personMessage?.value).toEqual(personEvent)

            // Check behavioural-filter-match-event
            const filterMessage = messages.find(
                (m) => (m.value as ProducedEvent).payload.type === 'behavioural-filter-match-event'
            )
            expect(filterMessage?.key).toBe(`${team.id}:${personId}:${filterHash}:${date}`)
            expect(filterMessage?.value).toEqual(filterEvent)
        })

        it('should handle multiple events with correct partitioning', async () => {
            const events: ProducedEvent[] = [
                {
                    key: '1:person1:event1',
                    payload: { type: 'person-performed-event', personId: 'person1', eventName: 'event1', teamId: 1 },
                },
                {
                    key: '2:person2:event2',
                    payload: { type: 'person-performed-event', personId: 'person2', eventName: 'event2', teamId: 2 },
                },
                {
                    key: '1:person3:event3',
                    payload: { type: 'person-performed-event', personId: 'person3', eventName: 'event3', teamId: 1 },
                },
            ]

            await processor.testPublishEvents(events)

            // Check published messages
            const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_CDP_PERSON_PERFORMED_EVENT)
            expect(messages).toHaveLength(3)

            // Verify messages have correct keys for partitioning
            expect(messages[0].key).toBe('1:person1:event1')
            expect(messages[1].key).toBe('2:person2:event2')
            expect(messages[2].key).toBe('1:person3:event3')

            // Verify message contents
            expect(messages[0].value).toEqual(events[0])
            expect(messages[1].value).toEqual(events[1])
            expect(messages[2].value).toEqual(events[2])
        })
    })
})
