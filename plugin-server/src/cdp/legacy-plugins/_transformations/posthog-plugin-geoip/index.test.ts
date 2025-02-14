import { City } from '@maxmind/geoip2-node'
import { createPageview, resetMeta } from '@posthog/plugin-scaffold/test/utils'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'

describe('posthog-plugin-geoip', () => {
    function resetMetaWithMmdb(
        transformResult = (res: City) => res as Record<string, any>
    ): LegacyTransformationPluginMeta {
        return resetMeta({
            geoip: {
                locate: (ipAddress: string) => {
                    const res = mmdb.city(ipAddress)
                    return transformResult(res)
                },
            },
            logger: {
                log: jest.fn(),
                error: jest.fn(),
            },
        }) as LegacyTransformationPluginMeta
    }

    test('event is enriched with IP location', () => {
        const event = processEvent({ ...createPageview(), ip: '89.160.20.129' }, resetMetaWithMmdb())
        expect(event!.properties).toEqual(
            expect.objectContaining({
                $geoip_city_name: 'Linköping',
                $geoip_country_name: 'Sweden',
                $geoip_country_code: 'SE',
                $geoip_continent_name: 'Europe',
                $geoip_continent_code: 'EU',
                $geoip_latitude: 58.4167,
                $geoip_longitude: 15.6167,
                $geoip_accuracy_radius: 76,
                $geoip_time_zone: 'Europe/Stockholm',
                $geoip_subdivision_1_code: 'E',
                $geoip_subdivision_1_name: 'Östergötland County',
            })
        )
    })

    test('person is enriched with IP location', () => {
        const event = processEvent({ ...createPageview(), ip: '89.160.20.129' }, resetMetaWithMmdb())
        expect(event!.properties!.$set).toEqual(
            expect.objectContaining({
                $geoip_city_name: 'Linköping',
                $geoip_country_name: 'Sweden',
                $geoip_country_code: 'SE',
                $geoip_continent_name: 'Europe',
                $geoip_continent_code: 'EU',
                $geoip_latitude: 58.4167,
                $geoip_longitude: 15.6167,
                $geoip_time_zone: 'Europe/Stockholm',
                $geoip_subdivision_1_code: 'E',
                $geoip_subdivision_1_name: 'Östergötland County',
            })
        )
        expect(event!.properties!.$set_once).toEqual(
            expect.objectContaining({
                $initial_geoip_city_name: 'Linköping',
                $initial_geoip_country_name: 'Sweden',
                $initial_geoip_country_code: 'SE',
                $initial_geoip_continent_name: 'Europe',
                $initial_geoip_continent_code: 'EU',
                $initial_geoip_latitude: 58.4167,
                $initial_geoip_longitude: 15.6167,
                $initial_geoip_time_zone: 'Europe/Stockholm',
                $initial_geoip_subdivision_1_code: 'E',
                $initial_geoip_subdivision_1_name: 'Östergötland County',
            })
        )
    })

    test('person props default to null if no values present', () => {
        const removeCityNameFromLookupResult = (res: City) => {
            const { city, ...remainingResult } = res
            return remainingResult
        }
        const event = processEvent(
            { ...createPageview(), ip: '89.160.20.129' },
            resetMetaWithMmdb(removeCityNameFromLookupResult)
        )
        expect(event!.properties!.$set).toMatchInlineSnapshot(`
            {
              "$geoip_accuracy_radius": 76,
              "$geoip_city_confidence": null,
              "$geoip_city_name": null,
              "$geoip_continent_code": "EU",
              "$geoip_continent_name": "Europe",
              "$geoip_country_code": "SE",
              "$geoip_country_name": "Sweden",
              "$geoip_latitude": 58.4167,
              "$geoip_longitude": 15.6167,
              "$geoip_postal_code": null,
              "$geoip_subdivision_1_code": "E",
              "$geoip_subdivision_1_name": "Östergötland County",
              "$geoip_subdivision_2_code": null,
              "$geoip_subdivision_2_name": null,
              "$geoip_time_zone": "Europe/Stockholm",
            }
        `)
        expect(event!.properties!.$set_once).toMatchInlineSnapshot(`
            {
              "$initial_geoip_accuracy_radius": 76,
              "$initial_geoip_city_confidence": null,
              "$initial_geoip_city_name": null,
              "$initial_geoip_continent_code": "EU",
              "$initial_geoip_continent_name": "Europe",
              "$initial_geoip_country_code": "SE",
              "$initial_geoip_country_name": "Sweden",
              "$initial_geoip_latitude": 58.4167,
              "$initial_geoip_longitude": 15.6167,
              "$initial_geoip_postal_code": null,
              "$initial_geoip_subdivision_1_code": "E",
              "$initial_geoip_subdivision_1_name": "Östergötland County",
              "$initial_geoip_subdivision_2_code": null,
              "$initial_geoip_subdivision_2_name": null,
              "$initial_geoip_time_zone": "Europe/Stockholm",
            }
        `)
    })

    test('event is skipped using $geoip_disable', () => {
        const testEvent = { ...createPageview(), ip: '89.160.20.129', properties: { $geoip_disable: true } }
        const processedEvent = processEvent(JSON.parse(JSON.stringify(testEvent)), resetMetaWithMmdb())
        expect(testEvent).toEqual(processedEvent)
    })
})
