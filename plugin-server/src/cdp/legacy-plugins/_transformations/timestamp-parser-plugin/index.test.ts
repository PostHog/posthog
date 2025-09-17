import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { processEvent } from './index'

const createEvent = (event: Partial<PluginEvent>): PluginEvent =>
    ({
        distinct_id: '1',
        event: '$pageview',
        properties: {
            ...event.properties,
        },
        ...event,
    }) as unknown as PluginEvent

describe('timestamp parser plugin', () => {
    it('should parse unix timestamp', () => {
        const event = createEvent({
            event: 'Monday 27/01/2021',
            properties: { $time: 1611772203.557, keepMe: 'nothing changes' },
            timestamp: '2021-01-27T10:30:03.557Z',
        })

        expect(processEvent(event, {} as any)).toEqual({
            ...event,
            properties: {
                ...event.properties,
                day_of_the_week: 'Wednesday',
                day: 27,
                month: 1,
                year: 2021,
            },
        })
    })

    it('should parse unix date', () => {
        const event = createEvent({
            event: 'Monday 27/01/2021',
            properties: { $time: 1611772203.557, keepMe: 'nothing changes' },
            timestamp: '2021-01-27',
        })

        expect(processEvent(event, {} as any)).toEqual({
            ...event,
            properties: {
                ...event.properties,
                day_of_the_week: 'Wednesday',
                day: 27,
                month: 1,
                year: 2021,
            },
        })
    })

    it('should parse numeric timestamp (just in case)', () => {
        const event = createEvent({
            event: 'Monday 27/01/2021',
            properties: { $time: 1611772203.557, keepMe: 'nothing changes' },
            timestamp: DateTime.fromISO('2021-01-27T10:30:03.557Z').toMillis() as unknown as string,
        })

        expect(processEvent(event, {} as any)).toEqual({
            ...event,
            properties: {
                ...event.properties,
                day_of_the_week: 'Wednesday',
                day: 27,
                month: 1,
                year: 2021,
            },
        })
    })

    it('processEvent does not crash without timestamp', () => {
        const event0 = createEvent({ event: '$identify' })
        const event1 = processEvent(event0, {} as any)
        expect(event1).toEqual(event0)
    })
})
