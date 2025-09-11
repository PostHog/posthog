import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'
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

const global = {
    propertiesToFilter: [
        'gender',
        '$set.gender',
        '$set.age',
        'foo.bar.baz.one',
        'nonExisting',
        '$set.$not_in_props',
        'no-such.with-dot',
    ],
}

const meta: LegacyTransformationPluginMeta = {
    global,
    config: {},
} as unknown as LegacyTransformationPluginMeta

const properties = {
    properties: {
        name: 'Mr. Hog',
        gender: 'male',
        age: 12,
        $set: {
            age: 35,
            pet: 'dog',
            firstName: 'Post',
            gender: 'female',
        },
        foo: {
            bar: {
                baz: {
                    one: 'one',
                    two: 'two',
                },
            },
        },
    },
}

test('event properties are filtered', () => {
    const event = processEvent(createEvent(properties), meta)
    expect(event.properties).not.toHaveProperty('gender')
    expect(event.properties.$set).not.toHaveProperty('age')
    expect(event.properties.foo.bar.baz).not.toHaveProperty('one')
    expect(event.properties).toHaveProperty('name')
    expect(event.properties).toHaveProperty('$set')
    expect(event.properties).toHaveProperty('foo')
    expect(event.properties.$set).toHaveProperty('firstName', 'Post')
    expect(event.properties.foo.bar.baz).toHaveProperty('two', 'two')
    expect(event.properties).toEqual({
        name: 'Mr. Hog',
        age: 12,
        $set: {
            pet: 'dog',
            firstName: 'Post',
        },
        foo: {
            bar: {
                baz: {
                    two: 'two',
                },
            },
        },
    })
})

const emptyProperties = {}

test('event properties are empty when no properties are given', () => {
    const event = processEvent(createEvent(emptyProperties), meta)

    expect(event.properties).not.toHaveProperty('$set')
    expect(event.properties).not.toHaveProperty('foo')
})
