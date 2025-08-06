import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { AggregatedBehaviouralEvent, CdpAggregationWriterConsumer } from './cdp-aggregation-writer.consumer'
import { CohortFilterPayload, PersonEventPayload, ProducedEvent } from './cdp-behavioural-events.consumer'

jest.setTimeout(20_000)

describe('CdpAggregationWriterConsumer', () => {
    let processor: CdpAggregationWriterConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        processor = new CdpAggregationWriterConsumer(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('Message Parsing', () => {
        it('should parse and separate person-performed-events and behavioural-filter-match-events', async () => {
            const personEvent: ProducedEvent = {
                key: `${team.id}:person1:event1`,
                payload: {
                    type: 'person-performed-event',
                    personId: 'person1',
                    eventName: 'event1',
                    teamId: team.id,
                },
            }

            const filterEvent: ProducedEvent = {
                key: `${team.id}:person1:hash123:2023-01-01`,
                payload: {
                    type: 'behavioural-filter-match-event',
                    teamId: team.id,
                    personId: 'person1',
                    filterHash: 'hash123',
                    date: '2023-01-01',
                },
            }

            const messages = [
                {
                    value: Buffer.from(JSON.stringify(personEvent)),
                } as any,
                {
                    value: Buffer.from(JSON.stringify(filterEvent)),
                } as any,
            ]

            const parsedBatch = await processor._parseKafkaBatch(messages)

            expect(parsedBatch.personPerformedEvents).toHaveLength(1)
            expect(parsedBatch.behaviouralFilterMatchedEvents).toHaveLength(1)

            expect(parsedBatch.personPerformedEvents[0]).toEqual({
                type: 'person-performed-event',
                personId: 'person1',
                eventName: 'event1',
                teamId: team.id,
            })

            expect(parsedBatch.behaviouralFilterMatchedEvents[0]).toEqual({
                type: 'behavioural-filter-match-event',
                teamId: team.id,
                personId: 'person1',
                filterHash: 'hash123',
                date: '2023-01-01',
            })
        })

        it('should handle multiple events of each type', async () => {
            const events: ProducedEvent[] = [
                {
                    key: '1:person1:event1',
                    payload: {
                        type: 'person-performed-event',
                        personId: 'person1',
                        eventName: 'event1',
                        teamId: 1,
                    },
                },
                {
                    key: '1:person1:hash1:2023-01-01',
                    payload: {
                        type: 'behavioural-filter-match-event',
                        teamId: 1,
                        personId: 'person1',
                        filterHash: 'hash1',
                        date: '2023-01-01',
                    },
                },
                {
                    key: '2:person2:event2',
                    payload: {
                        type: 'person-performed-event',
                        personId: 'person2',
                        eventName: 'event2',
                        teamId: 2,
                    },
                },
                {
                    key: '2:person2:hash2:2023-01-02',
                    payload: {
                        type: 'behavioural-filter-match-event',
                        teamId: 2,
                        personId: 'person2',
                        filterHash: 'hash2',
                        date: '2023-01-02',
                    },
                },
            ]

            const messages = events.map((event) => ({
                value: Buffer.from(JSON.stringify(event)),
            })) as any[]

            const parsedBatch = await processor._parseKafkaBatch(messages)

            expect(parsedBatch.personPerformedEvents).toHaveLength(2)
            expect(parsedBatch.behaviouralFilterMatchedEvents).toHaveLength(2)

            // Verify person performed events
            expect(parsedBatch.personPerformedEvents[0]).toMatchObject({
                personId: 'person1',
                eventName: 'event1',
                teamId: 1,
            })
            expect(parsedBatch.personPerformedEvents[1]).toMatchObject({
                personId: 'person2',
                eventName: 'event2',
                teamId: 2,
            })

            // Verify behavioural filter matched events
            expect(parsedBatch.behaviouralFilterMatchedEvents[0]).toMatchObject({
                personId: 'person1',
                filterHash: 'hash1',
                date: '2023-01-01',
                teamId: 1,
            })
            expect(parsedBatch.behaviouralFilterMatchedEvents[1]).toMatchObject({
                personId: 'person2',
                filterHash: 'hash2',
                date: '2023-01-02',
                teamId: 2,
            })
        })

        it('should handle empty batch', async () => {
            const parsedBatch = await processor._parseKafkaBatch([])
            expect(parsedBatch.personPerformedEvents).toHaveLength(0)
            expect(parsedBatch.behaviouralFilterMatchedEvents).toHaveLength(0)
        })
    })

    describe('Deduplication and Aggregation', () => {
        describe('deduplicatePersonPerformedEvents', () => {
            it('should deduplicate identical person performed events', () => {
                const events: PersonEventPayload[] = [
                    {
                        type: 'person-performed-event',
                        personId: 'person1',
                        eventName: 'pageview',
                        teamId: 1,
                    },
                    {
                        type: 'person-performed-event',
                        personId: 'person1',
                        eventName: 'pageview',
                        teamId: 1,
                    },
                    {
                        type: 'person-performed-event',
                        personId: 'person1',
                        eventName: 'click',
                        teamId: 1,
                    },
                ]

                const deduplicated = processor['deduplicatePersonPerformedEvents'](events)

                expect(deduplicated).toHaveLength(2)
                expect(deduplicated).toEqual([
                    {
                        type: 'person-performed-event',
                        personId: 'person1',
                        eventName: 'pageview',
                        teamId: 1,
                    },
                    {
                        type: 'person-performed-event',
                        personId: 'person1',
                        eventName: 'click',
                        teamId: 1,
                    },
                ])
            })
        })

        describe('aggregateBehaviouralFilterMatchedEvents', () => {
            it('should aggregate identical behavioural filter matched events with counter', () => {
                const events: CohortFilterPayload[] = [
                    {
                        type: 'behavioural-filter-match-event',
                        teamId: 1,
                        personId: 'person1',
                        filterHash: 'hash123',
                        date: '2023-01-01',
                    },
                    {
                        type: 'behavioural-filter-match-event',
                        teamId: 1,
                        personId: 'person1',
                        filterHash: 'hash123',
                        date: '2023-01-01',
                    },
                    {
                        type: 'behavioural-filter-match-event',
                        teamId: 1,
                        personId: 'person1',
                        filterHash: 'hash123',
                        date: '2023-01-01',
                    },
                    {
                        type: 'behavioural-filter-match-event',
                        teamId: 1,
                        personId: 'person1',
                        filterHash: 'hash456',
                        date: '2023-01-01',
                    },
                ]

                const aggregated = processor['aggregateBehaviouralFilterMatchedEvents'](events)

                expect(aggregated).toHaveLength(2)

                const firstEvent = aggregated.find((e) => e.filterHash === 'hash123')
                const secondEvent = aggregated.find((e) => e.filterHash === 'hash456')

                expect(firstEvent).toEqual({
                    type: 'behavioural-filter-match-event',
                    teamId: 1,
                    personId: 'person1',
                    filterHash: 'hash123',
                    date: '2023-01-01',
                    counter: 3,
                })

                expect(secondEvent).toEqual({
                    type: 'behavioural-filter-match-event',
                    teamId: 1,
                    personId: 'person1',
                    filterHash: 'hash456',
                    date: '2023-01-01',
                    counter: 1,
                })
            })
        })

        describe('processBatch integration with separate arrays', () => {
            it('should process events into separate arrays for postgres write', async () => {
                // Mock writeToPostgres to capture the arguments
                let capturedPersonEvents: PersonEventPayload[] = []
                let capturedBehaviouralEvents: AggregatedBehaviouralEvent[] = []

                processor['writeToPostgres'] = jest
                    .fn()
                    .mockImplementation(
                        async (personEvents: PersonEventPayload[], behaviouralEvents: AggregatedBehaviouralEvent[]) => {
                            capturedPersonEvents = personEvents
                            capturedBehaviouralEvents = behaviouralEvents
                            return Promise.resolve()
                        }
                    )

                const parsedBatch = {
                    personPerformedEvents: [
                        { type: 'person-performed-event' as const, teamId: 1, personId: 'person1', eventName: 'click' },
                        { type: 'person-performed-event' as const, teamId: 1, personId: 'person1', eventName: 'click' }, // duplicate
                        {
                            type: 'person-performed-event' as const,
                            teamId: 1,
                            personId: 'person1',
                            eventName: 'pageview',
                        },
                    ],
                    behaviouralFilterMatchedEvents: [
                        {
                            type: 'behavioural-filter-match-event' as const,
                            teamId: 1,
                            personId: 'person1',
                            filterHash: 'hash123',
                            date: '2023-01-01',
                        },
                        {
                            type: 'behavioural-filter-match-event' as const,
                            teamId: 1,
                            personId: 'person1',
                            filterHash: 'hash123',
                            date: '2023-01-01',
                        }, // duplicate
                        {
                            type: 'behavioural-filter-match-event' as const,
                            teamId: 1,
                            personId: 'person1',
                            filterHash: 'hash123',
                            date: '2023-01-01',
                        }, // duplicate
                    ],
                }

                await processor['processBatch'](parsedBatch)

                // Verify writeToPostgres was called with separate arrays
                expect(processor['writeToPostgres']).toHaveBeenCalledWith(expect.any(Array), expect.any(Array))

                // Verify person events were deduplicated (3 -> 2)
                expect(capturedPersonEvents).toHaveLength(2)
                expect(capturedPersonEvents).toEqual([
                    { type: 'person-performed-event', teamId: 1, personId: 'person1', eventName: 'click' },
                    { type: 'person-performed-event', teamId: 1, personId: 'person1', eventName: 'pageview' },
                ])

                // Verify behavioural events were aggregated (3 -> 1 with counter: 3)
                expect(capturedBehaviouralEvents).toHaveLength(1)
                expect(capturedBehaviouralEvents[0]).toEqual({
                    type: 'behavioural-filter-match-event',
                    teamId: 1,
                    personId: 'person1',
                    filterHash: 'hash123',
                    date: '2023-01-01',
                    counter: 3,
                })
            })
        })
    })
})
