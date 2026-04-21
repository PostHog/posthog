import { GeoIp } from '~/utils/geoip'

import { PipelineEvent } from '../../types'

// Mirrors the property-setting logic from the GeoIP Hog transformation template
// (cdp/templates/_transformations/geoip/geoip.template.ts). These two code paths are
// mutually exclusive: cookieless events are enriched here (before IP is stripped),
// non-cookieless events are enriched by the Hog template. If the template's property
// list changes, update this function to match.
export function enrichGeoIPProperties(event: PipelineEvent, geoip: GeoIp): void {
    const ip = event.properties?.$ip
    if (!ip || typeof ip !== 'string' || event.properties?.$geoip_disable) {
        return
    }

    const response = geoip.city(ip)
    if (!response) {
        return
    }

    const location: Record<string, string | number | null | undefined> = {}

    if (response.city) {
        location['city_name'] = response.city.names?.en
    }
    if (response.country) {
        location['country_name'] = response.country.names?.en
        location['country_code'] = response.country.isoCode
    }
    if (response.continent) {
        location['continent_name'] = response.continent.names?.en
        location['continent_code'] = response.continent.code
    }
    if (response.postal) {
        location['postal_code'] = response.postal.code
    }
    if (response.location) {
        location['latitude'] = response.location.latitude
        location['longitude'] = response.location.longitude
        location['accuracy_radius'] = response.location.accuracyRadius
        location['time_zone'] = response.location.timeZone
    }
    if (response.subdivisions) {
        for (let i = 0; i < response.subdivisions.length; i++) {
            const subdivision = response.subdivisions[i]
            location[`subdivision_${i + 1}_code`] = subdivision.isoCode
            location[`subdivision_${i + 1}_name`] = subdivision.names?.en
        }
    }

    const properties = event.properties!
    properties.$set = properties.$set ?? {}
    properties.$set_once = properties.$set_once ?? {}

    for (const [key, value] of Object.entries(location)) {
        properties[`$geoip_${key}`] = value
        properties.$set[`$geoip_${key}`] = value
        properties.$set_once[`$initial_geoip_${key}`] = value
    }
}
