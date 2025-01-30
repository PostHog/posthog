import { PluginEvent } from '@posthog/plugin-scaffold'

const { processEvent } = require('../index')

const createEvent = (event: Partial<PluginEvent>): PluginEvent =>
    ({
        distinct_id: '1',
        event: '$pageview',
        properties: {
            ...event.properties,
        },
        ...event,
    } as unknown as PluginEvent)

test('processEvent adds the right properties', async () => {
    const event0 = createEvent({
        event: 'Monday 27/01/2021',
        properties: { $time: 1611772203.557, keepMe: 'nothing changes' },
    })

    const event1 = await processEvent(event0)
    expect(event1).toEqual({
        ...event0,
        properties: {
            ...event0.properties,
            day_of_the_week: 'Wednesday',
            day: '27',
            month: '01',
            year: '2021',
        },
    })

    const event2 = createEvent({
        event: 'Monday 25/01/2021',
        properties: { $time: 1611587425.118, keepMe: 'nothing changes' },
    })

    const event3 = await processEvent(event2)
    expect(event3).toEqual({
        ...event2,
        properties: {
            ...event2.properties,
            day_of_the_week: 'Monday',
            day: '25',
            month: '01',
            year: '2021',
        },
    })
})

test('processEvent does not crash with identify', async () => {
    const event0 = createEvent({ event: '$identify' })
    const event1 = await processEvent(event0)
    expect(event1).toEqual(event0)
})
