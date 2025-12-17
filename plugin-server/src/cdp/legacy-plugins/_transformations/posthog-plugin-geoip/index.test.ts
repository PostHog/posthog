import { City } from '@maxmind/geoip2-node'

import { createPageview, resetMeta } from '@posthog/plugin-scaffold/test/utils'

import { defaultConfig } from '../../../../config/config'
import { GeoIPService, GeoIp } from '../../../../utils/geoip'
import { parseJSON } from '../../../../utils/json-parse'
import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'

describe('posthog-plugin-geoip', () => {
    let geoip: GeoIp

    beforeAll(async () => {
        geoip = await new GeoIPService(defaultConfig).get()
    })

    function resetMetaWithMmdb(
        transformResult = (res: City) => res as Record<string, any>
    ): LegacyTransformationPluginMeta {
        return resetMeta({
            geoip: {
                locate: (ipAddress: string) => {
                    const res = geoip.city(ipAddress)
                    return transformResult(res!)
                },
            },
            logger: {
                log: jest.fn(),
                error: jest.fn(),
            },
        }) as LegacyTransformationPluginMeta
    }

    test('event is enriched with IP location', () => {
        const event = processEvent({ ...createPageview(), ip: '12.87.118.0' }, resetMetaWithMmdb())
        expect(event!.properties).toMatchInlineSnapshot(`
            {
              "$active_feature_flags": [
                "navigation-1775",
                "session-recording-player",
              ],
              "$browser": "Chrome",
              "$browser_version": 86,
              "$current_url": "http://localhost:8000/instance/status",
              "$device_id": "17554768afe5cb-0fc915d2a583cf-166f6152-1ea000-175543686ffdc5",
              "$geoip_accuracy_radius": 20,
              "$geoip_city_name": "Cleveland",
              "$geoip_continent_code": "NA",
              "$geoip_continent_name": "North America",
              "$geoip_country_code": "US",
              "$geoip_country_name": "United States",
              "$geoip_latitude": 41.5,
              "$geoip_longitude": -81.6938,
              "$geoip_postal_code": "44192",
              "$geoip_subdivision_1_code": "OH",
              "$geoip_subdivision_1_name": "Ohio",
              "$geoip_time_zone": "America/New_York",
              "$host": "localhost:8000",
              "$initial_referrer": "$direct",
              "$initial_referring_domain": "$direct",
              "$insert_id": "hgu2p36uvlc1b9dg",
              "$lib": "web",
              "$lib_version": "1.7.0-beta.1",
              "$os": "Mac OS X",
              "$pathname": "/instance/status",
              "$screen_height": 1120,
              "$screen_width": 1790,
              "$set": {
                "$geoip_accuracy_radius": 20,
                "$geoip_city_confidence": null,
                "$geoip_city_name": "Cleveland",
                "$geoip_continent_code": "NA",
                "$geoip_continent_name": "North America",
                "$geoip_country_code": "US",
                "$geoip_country_name": "United States",
                "$geoip_latitude": 41.5,
                "$geoip_longitude": -81.6938,
                "$geoip_postal_code": "44192",
                "$geoip_subdivision_1_code": "OH",
                "$geoip_subdivision_1_name": "Ohio",
                "$geoip_subdivision_2_code": null,
                "$geoip_subdivision_2_name": null,
                "$geoip_time_zone": "America/New_York",
              },
              "$set_once": {
                "$initial_geoip_accuracy_radius": 20,
                "$initial_geoip_city_confidence": null,
                "$initial_geoip_city_name": "Cleveland",
                "$initial_geoip_continent_code": "NA",
                "$initial_geoip_continent_name": "North America",
                "$initial_geoip_country_code": "US",
                "$initial_geoip_country_name": "United States",
                "$initial_geoip_latitude": 41.5,
                "$initial_geoip_longitude": -81.6938,
                "$initial_geoip_postal_code": "44192",
                "$initial_geoip_subdivision_1_code": "OH",
                "$initial_geoip_subdivision_1_name": "Ohio",
                "$initial_geoip_subdivision_2_code": null,
                "$initial_geoip_subdivision_2_name": null,
                "$initial_geoip_time_zone": "America/New_York",
              },
              "$time": 1606383312.494,
              "$user_id": "3erf45reXthrGser675waeHFAsbv4AsadfR",
              "distinct_id": "scbbAqF7uyrMmamV4QBzcA1rrm9wHNISdFweZz-mQ0",
              "has_slack_webhook": false,
              "posthog_version": "1.17.0",
              "token": "mre13a_SMBv9EwHAtdtTyutyy6AfO00OTPwaalaHPGgKLS",
            }
        `)
    })

    test('person is enriched with IP location', () => {
        const event = processEvent({ ...createPageview(), ip: '12.87.118.0' }, resetMetaWithMmdb())
        expect(event!.properties!.$set).toMatchInlineSnapshot(`
            {
              "$geoip_accuracy_radius": 20,
              "$geoip_city_confidence": null,
              "$geoip_city_name": "Cleveland",
              "$geoip_continent_code": "NA",
              "$geoip_continent_name": "North America",
              "$geoip_country_code": "US",
              "$geoip_country_name": "United States",
              "$geoip_latitude": 41.5,
              "$geoip_longitude": -81.6938,
              "$geoip_postal_code": "44192",
              "$geoip_subdivision_1_code": "OH",
              "$geoip_subdivision_1_name": "Ohio",
              "$geoip_subdivision_2_code": null,
              "$geoip_subdivision_2_name": null,
              "$geoip_time_zone": "America/New_York",
            }
        `)
        expect(event!.properties!.$set_once).toMatchInlineSnapshot(`
            {
              "$initial_geoip_accuracy_radius": 20,
              "$initial_geoip_city_confidence": null,
              "$initial_geoip_city_name": "Cleveland",
              "$initial_geoip_continent_code": "NA",
              "$initial_geoip_continent_name": "North America",
              "$initial_geoip_country_code": "US",
              "$initial_geoip_country_name": "United States",
              "$initial_geoip_latitude": 41.5,
              "$initial_geoip_longitude": -81.6938,
              "$initial_geoip_postal_code": "44192",
              "$initial_geoip_subdivision_1_code": "OH",
              "$initial_geoip_subdivision_1_name": "Ohio",
              "$initial_geoip_subdivision_2_code": null,
              "$initial_geoip_subdivision_2_name": null,
              "$initial_geoip_time_zone": "America/New_York",
            }
        `)
    })

    test('person props default to null if no values present', () => {
        const removeCityNameFromLookupResult = (res: City) => {
            const { city, ...remainingResult } = res
            return remainingResult
        }
        const event = processEvent(
            { ...createPageview(), ip: '12.87.118.0' },
            resetMetaWithMmdb(removeCityNameFromLookupResult)
        )
        expect(event!.properties!.$set).toMatchInlineSnapshot(`
            {
              "$geoip_accuracy_radius": 20,
              "$geoip_city_confidence": null,
              "$geoip_city_name": null,
              "$geoip_continent_code": "NA",
              "$geoip_continent_name": "North America",
              "$geoip_country_code": "US",
              "$geoip_country_name": "United States",
              "$geoip_latitude": 41.5,
              "$geoip_longitude": -81.6938,
              "$geoip_postal_code": "44192",
              "$geoip_subdivision_1_code": "OH",
              "$geoip_subdivision_1_name": "Ohio",
              "$geoip_subdivision_2_code": null,
              "$geoip_subdivision_2_name": null,
              "$geoip_time_zone": "America/New_York",
            }
        `)
        expect(event!.properties!.$set_once).toMatchInlineSnapshot(`
            {
              "$initial_geoip_accuracy_radius": 20,
              "$initial_geoip_city_confidence": null,
              "$initial_geoip_city_name": null,
              "$initial_geoip_continent_code": "NA",
              "$initial_geoip_continent_name": "North America",
              "$initial_geoip_country_code": "US",
              "$initial_geoip_country_name": "United States",
              "$initial_geoip_latitude": 41.5,
              "$initial_geoip_longitude": -81.6938,
              "$initial_geoip_postal_code": "44192",
              "$initial_geoip_subdivision_1_code": "OH",
              "$initial_geoip_subdivision_1_name": "Ohio",
              "$initial_geoip_subdivision_2_code": null,
              "$initial_geoip_subdivision_2_name": null,
              "$initial_geoip_time_zone": "America/New_York",
            }
        `)
    })

    test('event is skipped using $geoip_disable', () => {
        const testEvent = { ...createPageview(), ip: '12.87.118.0', properties: { $geoip_disable: true } }
        const processedEvent = processEvent(parseJSON(JSON.stringify(testEvent)), resetMetaWithMmdb())
        expect(testEvent).toEqual(processedEvent)
    })
})
