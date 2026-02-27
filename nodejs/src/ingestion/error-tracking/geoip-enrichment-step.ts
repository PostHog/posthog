import { PluginEvent } from '~/plugin-scaffold'
import { GeoIp } from '~/utils/geoip'

import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface GeoIPEnrichmentInput {
    event: PluginEvent
}

/**
 * Creates a step that enriches events with GeoIP data.
 * Wraps the existing GeoIp service as a pipeline step.
 *
 * Adds GeoIP properties directly to event.properties following the standard
 * PostHog property naming convention ($geoip_*).
 */
export function createGeoIPEnrichmentStep<T extends GeoIPEnrichmentInput>(geoip: GeoIp): ProcessingStep<T, T> {
    return function geoipEnrichmentStep(input) {
        const { event } = input

        // IP is in properties.$ip after sanitizeEvent runs during message parsing
        const ip = event.properties?.$ip as string | undefined

        // If no IP address, pass through without enrichment
        if (!ip) {
            return Promise.resolve(ok(input))
        }

        const city = geoip.city(ip)

        // If GeoIP lookup fails, pass through without enrichment
        if (!city) {
            return Promise.resolve(ok(input))
        }

        // Add GeoIP properties to the event
        const enrichedEvent: PluginEvent = {
            ...event,
            properties: {
                ...event.properties,
                $geoip_country_code: city.country?.isoCode,
                $geoip_city_name: city.city?.names?.en,
                $geoip_subdivision_1_code: city.subdivisions?.[0]?.isoCode,
                $geoip_subdivision_1_name: city.subdivisions?.[0]?.names?.en,
                $geoip_latitude: city.location?.latitude,
                $geoip_longitude: city.location?.longitude,
            },
        }

        return Promise.resolve(ok({ ...input, event: enrichedEvent }))
    }
}
