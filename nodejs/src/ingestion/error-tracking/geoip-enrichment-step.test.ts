import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { GeoIp } from '~/utils/geoip'

import { PipelineResultType, isOkResult } from '../pipelines/results'
import { createGeoIPEnrichmentStep } from './geoip-enrichment-step'

describe('createGeoIPEnrichmentStep', () => {
    let mockGeoIp: jest.Mocked<GeoIp>
    let step: ReturnType<typeof createGeoIPEnrichmentStep>

    beforeEach(() => {
        mockGeoIp = {
            city: jest.fn(),
        } as unknown as jest.Mocked<GeoIp>
        step = createGeoIPEnrichmentStep(mockGeoIp)
    })

    it('enriches event with GeoIP data when $ip is present in properties', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: { existing: 'property', $ip: '1.2.3.4' },
        })

        mockGeoIp.city.mockReturnValueOnce({
            country: { isoCode: 'US' },
            city: { names: { en: 'San Francisco' } },
            subdivisions: [{ isoCode: 'CA', names: { en: 'California' } }],
            location: { latitude: 37.7749, longitude: -122.4194 },
        } as any)

        const result = await step({ event })

        expect(result.type).toBe(PipelineResultType.OK)
        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({
                existing: 'property',
                $ip: '1.2.3.4',
                $geoip_country_code: 'US',
                $geoip_city_name: 'San Francisco',
                $geoip_subdivision_1_code: 'CA',
                $geoip_subdivision_1_name: 'California',
                $geoip_latitude: 37.7749,
                $geoip_longitude: -122.4194,
            })
        }
        expect(mockGeoIp.city).toHaveBeenCalledWith('1.2.3.4')
    })

    it('passes through event unchanged when IP is missing', async () => {
        const event = createTestPluginEvent({
            ip: null,
            event: '$exception',
            properties: { existing: 'property' },
        })

        const result = await step({ event })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({ existing: 'property' })
        }
        expect(mockGeoIp.city).not.toHaveBeenCalled()
    })

    it('passes through event unchanged when GeoIP lookup fails', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: { existing: 'property', $ip: '1.2.3.4' },
        })

        mockGeoIp.city.mockReturnValueOnce(null)

        const result = await step({ event })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({ existing: 'property', $ip: '1.2.3.4' })
        }
    })

    it('handles partial GeoIP data', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: { $ip: '1.2.3.4' },
        })

        mockGeoIp.city.mockReturnValueOnce({
            country: { isoCode: 'US' },
            // Missing city, subdivisions, and location
        } as any)

        const result = await step({ event })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toEqual({
                $ip: '1.2.3.4',
                $geoip_country_code: 'US',
                $geoip_city_name: undefined,
                $geoip_subdivision_1_code: undefined,
                $geoip_subdivision_1_name: undefined,
                $geoip_latitude: undefined,
                $geoip_longitude: undefined,
            })
        }
    })

    it('handles empty subdivisions array', async () => {
        const event = createTestPluginEvent({
            event: '$exception',
            properties: { $ip: '1.2.3.4' },
        })

        mockGeoIp.city.mockReturnValueOnce({
            country: { isoCode: 'US' },
            city: { names: { en: 'New York' } },
            subdivisions: [],
            location: { latitude: 40.7128, longitude: -74.006 },
        } as any)

        const result = await step({ event })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties?.$geoip_subdivision_1_code).toBeUndefined()
            expect(result.value.event.properties?.$geoip_subdivision_1_name).toBeUndefined()
        }
    })

    it('preserves original event structure', async () => {
        const originalEvent = createTestPluginEvent({
            event: '$exception',
            distinct_id: 'user-123',
            uuid: 'event-uuid',
            properties: { key: 'value', $ip: '1.2.3.4' },
        })

        mockGeoIp.city.mockReturnValueOnce({
            country: { isoCode: 'US' },
        } as any)

        const result = await step({ event: originalEvent })

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.distinct_id).toBe('user-123')
            expect(result.value.event.uuid).toBe('event-uuid')
            expect(result.value.event.event).toBe('$exception')
        }
    })
})
