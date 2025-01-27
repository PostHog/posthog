const { createEvent, getMeta, resetMeta } = require('@posthog/plugin-scaffold/test/utils')
const { randomBytes } = require('crypto')

const { processEvent, setupPlugin } = require('../index.ts')

beforeEach(() => {
    resetMeta({
        config: {
            percentage: '100',
        },
    })
})

test('processEvent filters event', () => {
    // Setup Plugin
    setupPlugin(getMeta())

    for (let i = 0; i < 100; i++) {
        const event0 = createEvent({ distinct_id: randomBytes(10).toString('hex') })
        const event1 = processEvent(event0, getMeta())
        expect(event1).toEqual(event0)
    }
})

test('processEvent filters 0 events at 0 percent', () => {
    resetMeta({
        config: {
            percentage: '0',
        },
    })

    // Setup Plugin
    setupPlugin(getMeta())

    // create a random event
    const event0 = createEvent({ event: 'blah' })

    for (let i = 0; i < 100; i++) {
        const event1 = processEvent(event0, getMeta())
        expect(event1).toBeNull()
    }
})



test('processEvent filters same events at different increasing percent', () => {

    // create an event. Hash generates 0.42
    const event0 = createEvent({ distinct_id: '1' })

    for (let i = 0; i < 5; i++) {
        resetMeta({
            config: {
                percentage: (i*10).toString(),
            },
        })
            // Setup Plugin
        setupPlugin(getMeta())

        const event1 = processEvent(event0, getMeta())
        expect(event1).toBeNull()
    }

    for (let i = 5; i <= 10; i++) {
        resetMeta({
            config: {
                percentage: (i*10).toString(),
            },
        })
            // Setup Plugin
        setupPlugin(getMeta())

        const event1 = processEvent(event0, getMeta())
        expect(event1).toEqual(event0)
    }
})

