import { GeoIPExtension } from '@posthog/plugin-scaffold'

import { Hub } from '../../../types'

export function createGeoIp(server: Hub): GeoIPExtension {
    return {
        locate: async function (ipAddress) {
            if (server.mmdb) {
                try {
                    return Promise.resolve(server.mmdb.city(ipAddress))
                } catch (e) {
                    // Return null if the lookup fails (unknown / invalid IP)
                    return Promise.resolve(null)
                }
            } else {
                return Promise.reject('geoip database is not ready')
            }
        },
    }
}
