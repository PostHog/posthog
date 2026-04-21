import { City } from '@maxmind/geoip2-node'

import { GeoIp } from '~/utils/geoip'

import { PipelineEvent } from '../../types'
import { enrichGeoIPProperties } from './cookieless-geoip'

function makeEvent(overrides: Partial<PipelineEvent> = {}): PipelineEvent {
    return {
        event: 'test',
        distinct_id: 'user1',
        properties: {
            $ip: '89.160.20.129',
            ...overrides.properties,
        },
        site_url: 'https://example.com',
        now: new Date().toISOString(),
        uuid: 'test-uuid',
        ip: null,
        ...overrides,
    }
}

function makeMockGeoIp(cityResult: Partial<City> | null = null): GeoIp {
    return {
        city: jest.fn().mockReturnValue(cityResult),
    }
}

const fullCityResponse: Partial<City> = {
    city: { names: { en: 'Linköping' }, geonameId: 1, confidence: undefined },
    country: { names: { en: 'Sweden' }, isoCode: 'SE', geonameId: 2, isInEuropeanUnion: true, confidence: undefined },
    continent: { names: { en: 'Europe' }, code: 'EU', geonameId: 3 },
    postal: { code: '58222', confidence: undefined },
    location: {
        latitude: 58.4167,
        longitude: 15.6167,
        accuracyRadius: 76,
        timeZone: 'Europe/Stockholm',
        metroCode: undefined,
        averageIncome: undefined,
        populationDensity: undefined,
    },
    subdivisions: [
        { names: { en: 'Östergötland County' }, isoCode: 'E', geonameId: 4, confidence: undefined },
    ],
} as unknown as City

describe('enrichGeoIPProperties', () => {
    it('should enrich event with full geoip data', () => {
        const event = makeEvent()
        const geoip = makeMockGeoIp(fullCityResponse)

        enrichGeoIPProperties(event, geoip)

        expect(geoip.city).toHaveBeenCalledWith('89.160.20.129')
        expect(event.properties!.$geoip_city_name).toBe('Linköping')
        expect(event.properties!.$geoip_country_name).toBe('Sweden')
        expect(event.properties!.$geoip_country_code).toBe('SE')
        expect(event.properties!.$geoip_continent_name).toBe('Europe')
        expect(event.properties!.$geoip_continent_code).toBe('EU')
        expect(event.properties!.$geoip_postal_code).toBe('58222')
        expect(event.properties!.$geoip_latitude).toBe(58.4167)
        expect(event.properties!.$geoip_longitude).toBe(15.6167)
        expect(event.properties!.$geoip_accuracy_radius).toBe(76)
        expect(event.properties!.$geoip_time_zone).toBe('Europe/Stockholm')
        expect(event.properties!.$geoip_subdivision_1_code).toBe('E')
        expect(event.properties!.$geoip_subdivision_1_name).toBe('Östergötland County')
    })

    it('should set $set and $set_once properties', () => {
        const event = makeEvent()
        const geoip = makeMockGeoIp(fullCityResponse)

        enrichGeoIPProperties(event, geoip)

        expect(event.properties!.$set.$geoip_country_name).toBe('Sweden')
        expect(event.properties!.$set.$geoip_city_name).toBe('Linköping')
        expect(event.properties!.$set_once.$initial_geoip_country_name).toBe('Sweden')
        expect(event.properties!.$set_once.$initial_geoip_city_name).toBe('Linköping')
    })

    it('should not enrich when $geoip_disable is set', () => {
        const event = makeEvent({ properties: { $ip: '89.160.20.129', $geoip_disable: true } })
        const geoip = makeMockGeoIp(fullCityResponse)

        enrichGeoIPProperties(event, geoip)

        expect(geoip.city).not.toHaveBeenCalled()
        expect(event.properties!.$geoip_country_name).toBeUndefined()
    })

    it('should not enrich when $ip is missing', () => {
        const event = makeEvent({ properties: {} })
        const geoip = makeMockGeoIp(fullCityResponse)

        enrichGeoIPProperties(event, geoip)

        expect(geoip.city).not.toHaveBeenCalled()
    })

    it('should not enrich when $ip is not a string', () => {
        const event = makeEvent({ properties: { $ip: 12345 } })
        const geoip = makeMockGeoIp(fullCityResponse)

        enrichGeoIPProperties(event, geoip)

        expect(geoip.city).not.toHaveBeenCalled()
    })

    it('should not enrich when geoip lookup returns null', () => {
        const event = makeEvent()
        const geoip = makeMockGeoIp(null)

        enrichGeoIPProperties(event, geoip)

        expect(geoip.city).toHaveBeenCalledWith('89.160.20.129')
        expect(event.properties!.$geoip_country_name).toBeUndefined()
    })

    it('should handle partial geoip response (country only)', () => {
        const event = makeEvent()
        const geoip = makeMockGeoIp({
            country: { names: { en: 'Germany' }, isoCode: 'DE', geonameId: 1, isInEuropeanUnion: true, confidence: undefined },
        } as unknown as City)

        enrichGeoIPProperties(event, geoip)

        expect(event.properties!.$geoip_country_name).toBe('Germany')
        expect(event.properties!.$geoip_country_code).toBe('DE')
        expect(event.properties!.$geoip_city_name).toBeUndefined()
        expect(event.properties!.$geoip_latitude).toBeUndefined()
    })

    it('should initialize $set and $set_once if not already present', () => {
        const event = makeEvent()
        delete event.properties!.$set
        delete event.properties!.$set_once
        const geoip = makeMockGeoIp(fullCityResponse)

        enrichGeoIPProperties(event, geoip)

        expect(event.properties!.$set).toBeDefined()
        expect(event.properties!.$set_once).toBeDefined()
        expect(event.properties!.$set.$geoip_country_name).toBe('Sweden')
    })
})
