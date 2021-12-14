import { DateTime, Settings } from 'luxon'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { detectDateFormat, EventPropertyCounter } from '../../../src/worker/ingestion/event-property-counter'
import { resetTestDatabase } from '../../helpers/sql'

describe('EventPropertyCounter()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let eventPropertyCounter: EventPropertyCounter

    beforeEach(async () => {
        Settings.now = () => new Date('2015-04-04T04:04:04.000Z').getTime()
        ;[hub, closeHub] = await createHub({ EXPERIMENTAL_EVENT_PROPERTY_COUNTER: true })
        await resetTestDatabase()
        eventPropertyCounter = hub.eventPropertyCounter
    })

    afterEach(async () => {
        await closeHub()
    })

    describe('updateEventPropertyCounter()', () => {
        beforeEach(async () => {
            await hub.db.postgresQuery("UPDATE posthog_team SET ingested_event = 't'", undefined, 'testTag')
            await hub.db.postgresQuery('DELETE FROM posthog_eventdefinition', undefined, 'testTag')
            await hub.db.postgresQuery('DELETE FROM posthog_propertydefinition', undefined, 'testTag')
            await hub.db.postgresQuery('DELETE FROM posthog_eventproperty', undefined, 'testTag')
        })

        it('upserts event properties', async () => {
            for (let run = 0; run++; run < 3) {
                await eventPropertyCounter.updateEventPropertyCounter(2, 'new-event', {
                    property_name: 'efg',
                    number: 4,
                    booly: true,
                })
                await eventPropertyCounter.flush()

                const eventProperties = await hub.db.fetchEventProperties()
                expect(eventProperties).toEqual([
                    {
                        id: expect.any(Number),
                        event: 'new-event',
                        property: 'property_name',
                        property_type: 'STRING',
                        property_type_format: null,
                        total_volume: run,
                        created_at: '2015-04-04T04:04:04.000Z',
                        last_seen_at: '2015-04-04T04:04:04.000Z',
                    },
                    {
                        id: expect.any(Number),
                        event: 'new-event',
                        property: 'number',
                        property_type: 'NUMBER',
                        property_type_format: null,
                        total_volume: run,
                        created_at: '2015-04-04T04:04:04.000Z',
                        last_seen_at: '2015-04-04T04:04:04.000Z',
                    },
                    {
                        id: expect.any(Number),
                        event: 'new-event',
                        property: 'booly',
                        property_type: 'BOOLEAN',
                        property_type_format: null,
                        total_volume: run,
                        created_at: '2015-04-04T04:04:04.000Z',
                        last_seen_at: '2015-04-04T04:04:04.000Z',
                    },
                ])
            }
        })

        it('flushes every 2 minutes', async () => {
            jest.spyOn(EventPropertyCounter.prototype, 'flush')

            await eventPropertyCounter.updateEventPropertyCounter(2, 'new-event', { key: 'value' })
            expect(eventPropertyCounter.flush).toHaveBeenCalledTimes(0)
            expect(eventPropertyCounter.lastFlushAt).toEqual(DateTime.fromISO('2015-04-04T04:04:04.000Z'))

            // 2 min and 2 sec later
            Settings.now = () => new Date('2015-04-04T04:06:06.000Z').getTime()
            await eventPropertyCounter.updateEventPropertyCounter(2, 'new-event', { key: 'value' })
            expect(eventPropertyCounter.flush).toHaveBeenCalledTimes(1)
            expect(eventPropertyCounter.lastFlushAt).toEqual(DateTime.fromISO('2015-04-04T04:06:06.000Z'))

            const eventProperties = await hub.db.fetchEventProperties()
            expect(eventProperties.length).toEqual(1)
        })

        it('flushes after 50k unique properties', async () => {
            jest.spyOn(EventPropertyCounter.prototype, 'flush')

            const properties: Record<string, any> = {}
            for (let i = 0; i < 49999; i++) {
                properties[`prop_${i}`] = i
            }
            await eventPropertyCounter.updateEventPropertyCounter(2, 'new-event', properties)
            expect(eventPropertyCounter.flush).toHaveBeenCalledTimes(0)
            expect(eventPropertyCounter.lastFlushAt).toEqual(DateTime.fromISO('2015-04-04T04:04:04.000Z'))

            // 1 sec later, not flushed
            Settings.now = () => new Date('2015-04-04T04:04:05.000Z').getTime()
            await eventPropertyCounter.updateEventPropertyCounter(2, 'new-event', { newProp: true })
            expect(eventPropertyCounter.flush).toHaveBeenCalledTimes(0)
            expect(eventPropertyCounter.lastFlushAt).toEqual(DateTime.fromISO('2015-04-04T04:04:04.000Z'))

            // last property to get over the 50k line
            await eventPropertyCounter.updateEventPropertyCounter(2, 'new-event', { lastProp: true })
            expect(eventPropertyCounter.flush).toHaveBeenCalledTimes(1)
            expect(eventPropertyCounter.lastFlushAt).toEqual(DateTime.fromISO('2015-04-04T04:04:05.000Z'))

            const eventProperties = await hub.db.fetchEventProperties()
            expect(eventProperties.length).toEqual(50001)
        })
    })

    describe('detectDateFormat', () => {
        const matches = [
            { value: '2021-01-21', response: 'YYYY-MM-DD' },
            { value: '2021-12-14T16:25:56.777Z', response: 'ISO8601-UTC' },
            { value: '2021-12-14T16:25:56.777+02:00', response: 'ISO8601-TZ' },
        ]

        for (const { value, response } of matches) {
            test(`${value} --> ${response}`, () => {
                expect(detectDateFormat(value)).toEqual(response)
            })
        }
    })
})
