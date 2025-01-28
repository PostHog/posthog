const {
    createEvent,
    createIdentify,
    createPageview,
    createCache,
    getMeta,
    resetMeta,
    clone,
} = require('@posthog/plugin-scaffold/test/utils.js')
const { setupPlugin, processEvent } = require('../index')


test('processEvent adds the right properties', async () => {

    const event0 = createEvent({ event: 'Monday 27/01/2021', properties: { $time: 1611772203.557, keepMe: 'nothing changes' } })

    const event1 = await processEvent(clone(event0), getMeta())
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

    const event2 = createEvent({ event: 'Monday 25/01/2021', properties: { $time: 1611587425.118, keepMe: 'nothing changes' } })

    const event3 = await processEvent(clone(event2), getMeta())
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
    const event0 = createIdentify()

    const event1 = await processEvent(clone(event0), getMeta())
    expect(event1).toEqual(event0)
})