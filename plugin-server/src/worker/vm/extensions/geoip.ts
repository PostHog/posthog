import { GeoIPExtension } from '@posthog/plugin-scaffold'

import { Hub } from '../../../types'

export function createGeoIp(server: Hub): GeoIPExtension {
    return {
        locate: async function (ipAddress) {
            if (server.mmdb) {
                return Promise.resolve(server.mmdb.city(ipAddress)).catch((_) => null)
            } else {
                return Promise.reject('geoip database is not ready')
            }
        },
    }
}
