import { GeoIPExtension } from '@posthog/plugin-scaffold'

import { Hub } from '../../../types'
import { logger } from '../../../utils/logger'

export function createGeoIp(server: Hub): GeoIPExtension {
    return {
        locate: async function (ipAddress) {
            if (server.mmdb) {
                try {
                    return Promise.resolve(server.mmdb.city(ipAddress))
                } catch (e) {
                    if (e.name != 'AddressNotFoundError') {
                        logger.warn('⚠️', 'geoip lookup failed', { ip: ipAddress, error: e })
                    }
                    return Promise.resolve(null)
                }
            } else {
                return Promise.reject('geoip database is not ready')
            }
        },
    }
}
