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
    } as unknown as PluginEvent)

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

const geoProperties = {
    properties: {
        $latitude: 40.7128,
        $longitude: -74.006,
        $geoip_latitude: 40.7128,
        $geoip_longitude: -74.006,
        $set: {
            $geoip_latitude: 40.7128,
            $geoip_longitude: -74.006,
            geoip_latitude: 40.7128,
            geoip_longitude: -74.006,
        },
        $set_once: {
            $initial_geoip_latitude: 40.7128,
            $initial_geoip_longitude: -74.006,
        },
        other_prop: 'should remain',
    },
}

test('geo properties are filtered', () => {
    const geoGlobal = {
        propertiesToFilter: [
            '$latitude',
            '$longitude',
            '$geoip_latitude',
            '$geoip_longitude',
            '$set.$geoip_latitude',
            '$set.$geoip_longitude',
            '$set.geoip_latitude',
            '$set.geoip_longitude',
            '$set_once.$initial_geoip_latitude',
            '$set_once.$initial_geoip_longitude',
        ],
    }
    const geoMeta = { ...meta, global: geoGlobal }
    const event = processEvent(createEvent(geoProperties), geoMeta)

    expect(event.properties).not.toHaveProperty('$latitude')
    expect(event.properties).not.toHaveProperty('$longitude')
    expect(event.properties).not.toHaveProperty('$geoip_latitude')
    expect(event.properties).not.toHaveProperty('$geoip_longitude')
    expect(event.properties.$set).not.toHaveProperty('$geoip_latitude')
    expect(event.properties.$set).not.toHaveProperty('$geoip_longitude')
    expect(event.properties.$set).not.toHaveProperty('geoip_latitude')
    expect(event.properties.$set).not.toHaveProperty('geoip_longitude')
    expect(event.properties.$set_once).not.toHaveProperty('$initial_geoip_latitude')
    expect(event.properties.$set_once).not.toHaveProperty('$initial_geoip_longitude')
    expect(event.properties).toHaveProperty('other_prop', 'should remain')
})

const ipAndGeoProperties = {
    properties: {
        $ip: '1.2.3.4',
        $geoip_latitude: 40.7128,
        $geoip_longitude: -74.006,
        $set: {
            $geoip_latitude: 40.7128,
            $geoip_longitude: -74.006,
        },
        $set_once: {
            $initial_geoip_latitude: 40.7128,
            $initial_geoip_longitude: -74.006,
        },
        other_prop: 'should remain',
    },
}

test('ip and geo properties are filtered', () => {
    const ipAndGeoGlobal = {
        propertiesToFilter: [
            '$ip',
            '$geoip_latitude',
            '$geoip_longitude',
            '$set.$geoip_latitude',
            '$set.$geoip_longitude',
            '$set_once.$initial_geoip_latitude',
            '$set_once.$initial_geoip_longitude',
        ],
    }
    const ipAndGeoMeta = { ...meta, global: ipAndGeoGlobal }
    const event = processEvent(createEvent(ipAndGeoProperties), ipAndGeoMeta)

    expect(event.ip).toBeNull()
    expect(event.properties).not.toHaveProperty('$ip')
    expect(event.properties).not.toHaveProperty('$geoip_latitude')
    expect(event.properties).not.toHaveProperty('$geoip_longitude')
    expect(event.properties.$set).not.toHaveProperty('$geoip_latitude')
    expect(event.properties.$set).not.toHaveProperty('$geoip_longitude')
    expect(event.properties.$set_once).not.toHaveProperty('$initial_geoip_latitude')
    expect(event.properties.$set_once).not.toHaveProperty('$initial_geoip_longitude')
    expect(event.properties).toHaveProperty('other_prop', 'should remain')
})
