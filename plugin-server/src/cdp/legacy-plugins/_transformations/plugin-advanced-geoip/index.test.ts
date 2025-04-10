import { PluginEvent } from '@posthog/plugin-scaffold'
import { createPageview, resetMeta } from '@posthog/plugin-scaffold/test/utils'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'

const defaultMeta = {
    config: {
        discardIp: 'true',
        discardLibs: 'posthog-node',
    },
    logger: {
        log: jest.fn(),
        warn: jest.fn(),
    },
}

const createGeoIPPageview = (): PluginEvent => {
    const event = createPageview()

    const setGeoIPProps = {
        $geoip_city_name: 'Ashburn',
        $geoip_country_name: 'United States',
        $geoip_country_code: 'US',
        $geoip_continent_name: 'North America',
        $geoip_continent_code: 'NA',
        $geoip_postal_code: '20149',
        $geoip_latitude: 39.0469,
        $geoip_longitude: -77.4903,
        $geoip_time_zone: 'America/New_York',
        $geoip_subdivision_1_code: 'VA',
        $geoip_subdivision_1_name: 'Virginia',
    }

    const setOnceGeoIPProps = {
        $initial_geoip_city_name: 'Ashburn',
        $initial_geoip_country_name: 'United States',
        $initial_geoip_country_code: 'US',
        $initial_geoip_continent_name: 'North America',
        $initial_geoip_continent_code: 'NA',
        $initial_geoip_postal_code: '20149',
        $initial_geoip_latitude: 39.0469,
        $initial_geoip_longitude: -77.4903,
        $initial_geoip_time_zone: 'America/New_York',
        $initial_geoip_subdivision_1_code: 'VA',
        $initial_geoip_subdivision_1_name: 'Virginia',
    }

    const properties = {
        ...event.properties,
        $ip: '13.106.122.3',
        $plugins_succeeded: ['GeoIP (8199)', 'Unduplicates (8303)'],
        $lib: 'posthog-node',
        $set: setGeoIPProps,
        $set_once: setOnceGeoIPProps,
    }
    return {
        ...event,
        ip: '13.106.122.3',
        properties,
        $set: setGeoIPProps,
        $set_once: setOnceGeoIPProps,
    }
}

const helperVerifyGeoIPIsEmpty = (event: PluginEvent): void => {
    // event properties
    expect(event!.properties!.$geoip_city_name).toEqual(undefined)
    expect(event!.properties!.$geoip_country_name).toEqual(undefined)
    expect(event!.properties!.$geoip_country_code).toEqual(undefined)

    // $set
    expect(event!.$set!.$geoip_city_name).toEqual(undefined)
    expect(event!.$set!.$geoip_country_name).toEqual(undefined)
    expect(event!.$set!.$geoip_country_code).toEqual(undefined)
    expect(event!.$set!.$geoip_continent_name).toEqual(undefined)
    expect(event!.$set!.$geoip_continent_code).toEqual(undefined)
    expect(event!.$set!.$geoip_postal_code).toEqual(undefined)
    expect(event!.$set!.$geoip_latitude).toEqual(undefined)
    expect(event!.$set!.$geoip_longitude).toEqual(undefined)
    expect(event!.$set!.$geoip_time_zone).toEqual(undefined)
    expect(event!.$set!.$geoip_subdivision_1_code).toEqual(undefined)
    expect(event!.$set!.$geoip_subdivision_1_name).toEqual(undefined)

    // $set_once
    expect(event!.$set_once!.$initial_geoip_city_name).toEqual(undefined)
    expect(event!.$set_once!.$initial_geoip_country_name).toEqual(undefined)
    expect(event!.$set_once!.$initial_geoip_country_code).toEqual(undefined)
    expect(event!.$set_once!.$initial_geoip_latitude).toEqual(undefined)
    expect(event!.$set_once!.$initial_geoip_longitude).toEqual(undefined)

    // $set on event props
    expect(event!.properties!.$set!.$geoip_city_name).toEqual(undefined)
    expect(event!.properties!.$set!.$geoip_country_name).toEqual(undefined)
    expect(event!.properties!.$set!.$geoip_country_code).toEqual(undefined)

    // $set_once on event props
    expect(event!.properties!.$set_once!.$initial_geoip_city_name).toEqual(undefined)
    expect(event!.properties!.$set_once!.$initial_geoip_country_name).toEqual(undefined)
    expect(event!.properties!.$set_once!.$initial_geoip_country_code).toEqual(undefined)
}

describe('plugin-advanced-geoip', () => {
    describe('discard IP', () => {
        test('IP is discarded', () => {
            const meta = resetMeta(defaultMeta) as LegacyTransformationPluginMeta
            const event = processEvent(createGeoIPPageview(), meta)
            expect(event?.ip).toEqual(null)
            expect(event?.properties?.$ip).toEqual(undefined)
        })
        test('IP is not discarded if not enabled', () => {
            const meta = resetMeta({
                ...defaultMeta,
                config: { ...defaultMeta.config, discardIp: 'false' },
            }) as LegacyTransformationPluginMeta
            const event = processEvent(createGeoIPPageview(), meta)
            expect(event?.ip).toEqual('13.106.122.3')
            expect(event?.properties?.$ip).toEqual('13.106.122.3')
        })
        test('IP is not discarded if GeoIP not processed', () => {
            const meta = resetMeta(defaultMeta) as LegacyTransformationPluginMeta
            const preprocessedEvent = createGeoIPPageview()
            preprocessedEvent.properties = {
                ...preprocessedEvent.properties,
                $plugins_succeeded: ['Unduplicates (8303)'],
            }
            const event = processEvent(preprocessedEvent, meta)
            expect(event?.ip).toEqual('13.106.122.3')
            expect(event?.properties?.$ip).toEqual('13.106.122.3')
        })
    })

    describe('$lib ignore', () => {
        test('ignores GeoIP from $lib', () => {
            const meta = resetMeta(defaultMeta) as LegacyTransformationPluginMeta
            const event = processEvent(createGeoIPPageview(), meta)
            helperVerifyGeoIPIsEmpty(event!)
            expect(Object.keys(event!.$set!).length).toEqual(0) // Ensure this is not sending properties even as undefined (that overwrites the user properties)
            expect(Object.keys(event!.$set_once!).length).toEqual(0) // Ensure this is not sending properties even as undefined (that overwrites the user properties)
        })

        test('ignores GeoIP from $lib CSV', () => {
            const meta = resetMeta({
                ...defaultMeta,
                config: { ...defaultMeta.config, discardLibs: 'posthog-ios,posthog-android,posthog-node' },
            }) as LegacyTransformationPluginMeta
            const event = processEvent(createGeoIPPageview(), meta)
            helperVerifyGeoIPIsEmpty(event!)
        })

        test('keeps GeoIP if $lib is not on ignore list', () => {
            const meta = resetMeta(defaultMeta) as LegacyTransformationPluginMeta
            const preprocessedEvent = createGeoIPPageview()
            preprocessedEvent.properties!.$lib = 'posthog-swift'
            const event = processEvent(preprocessedEvent, meta)
            expect(event!.$set!.$geoip_city_name).toEqual('Ashburn')
            expect(event!.$set!.$geoip_country_name).toEqual('United States')
            expect(event!.$set!.$geoip_country_code).toEqual('US')

            expect(event!.$set_once!.$initial_geoip_city_name).toEqual('Ashburn')
            expect(event!.$set_once!.$initial_geoip_country_name).toEqual('United States')
            expect(event!.$set_once!.$initial_geoip_country_code).toEqual('US')
        })
    })
})
