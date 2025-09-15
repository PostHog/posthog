import { randomBytes } from 'crypto'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent, setupPlugin } from './index'

let meta: LegacyTransformationPluginMeta

const createEvent = (event: Partial<PluginEvent>): PluginEvent =>
    ({
        distinct_id: '1',
        event: '$pageview',
        properties: {
            $current_url: 'http://www.google.com',
            ...event.properties,
        },
        ...event,
    }) as unknown as PluginEvent

beforeEach(() => {
    meta = {
        global: {},
        config: {
            percentage: '100',
        },
    } as unknown as LegacyTransformationPluginMeta
})

test('processEvent filters event', () => {
    // Setup Plugin
    setupPlugin(meta)

    for (let i = 0; i < 100; i++) {
        const event0 = createEvent({ distinct_id: randomBytes(10).toString('hex') })
        const event1 = processEvent(event0, meta)
        expect(event1).toEqual(event0)
    }
})

test('processEvent filters 0 events at 0 percent', () => {
    meta.config.percentage = '0'

    // Setup Plugin
    setupPlugin(meta)

    // create a random event
    const event0 = createEvent({ event: 'blah' })

    for (let i = 0; i < 100; i++) {
        const event1 = processEvent(event0, meta)
        expect(event1).toBeNull()
    }
})

test('processEvent filters same events at different increasing percent', () => {
    // create an event. Hash generates 0.42
    const event0 = createEvent({ distinct_id: '1' })

    for (let i = 0; i < 5; i++) {
        meta.config.percentage = (i * 10).toString()

        // Setup Plugin
        setupPlugin(meta)

        const event1 = processEvent(event0, meta)
        expect(event1).toBeNull()
    }

    for (let i = 5; i <= 10; i++) {
        meta.config.percentage = (i * 10).toString()

        // Setup Plugin
        setupPlugin(meta)

        const event1 = processEvent(event0, meta)
        expect(event1).toEqual(event0)
    }
})

test('processEvent filters events based on triggering events', () => {
    // create an event. Hash generates 0.42
    const event0 = createEvent({ event: 'blah', distinct_id: '1' })

    for (let i = 0; i < 5; i++) {
        meta.config.percentage = (i * 10).toString()
        meta.config.triggeringEvents = 'blah,$pageview'

        // Setup Plugin
        setupPlugin(meta)

        const event1 = processEvent(event0, meta)
        expect(event1).toBeNull()
    }

    for (let i = 0; i < 5; i++) {
        meta.config.percentage = (i * 10).toString()
        meta.config.triggeringEvents = '$pageview'

        // Setup Plugin
        setupPlugin(meta)

        const event1 = processEvent(event0, meta)
        expect(event1).toEqual(event0)
    }
})
