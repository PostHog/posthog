import { City, Reader, ReaderModel } from '@maxmind/geoip2-node'
import { Counter } from 'prom-client'

import { Hub, PluginsServerConfig } from '../types'
import { status } from './status'

export type GeoIp = {
    city: (ip: string) => City | null
}

export const geoipCompareCounter = new Counter({
    name: 'cdp_geoip_compare_count',
    help: 'Number of times we compare the MMDB file to the local file',
    labelNames: ['result'],
})

export class GeoIPService {
    private _mmdbPromise: Promise<ReaderModel> | undefined

    constructor(private config: PluginsServerConfig) {
        status.info('🌎', 'GeoIPService created')
    }

    private getMmdb() {
        if (!this._mmdbPromise) {
            status.info('🌎', 'Loading MMDB from disk...', {
                location: this.config.MMDB_FILE_LOCATION,
            })
            this._mmdbPromise = Reader.open(this.config.MMDB_FILE_LOCATION)
                .then((mmdb) => {
                    status.info('🌎', 'Loading MMDB from disk succeeded!')
                    return mmdb
                })
                .catch((e) => {
                    status.warn('🌎', 'Loading MMDB from disk failed!', {
                        location: this.config.MMDB_FILE_LOCATION,
                        error: e.message,
                    })
                    throw e
                })
        }

        return this._mmdbPromise
    }

    async get(hub: Hub): Promise<GeoIp> {
        // NOTE: There is a lot of code here just testing that the values are the same as before.
        // Once released we don't need the Hub and can simplify this.
        let mmdb: ReaderModel | undefined
        try {
            mmdb = await this.getMmdb()
        } catch (e) {
            if (!this.config.MMDB_COMPARE_MODE) {
                // If we aren't comparing then we should fail hard
                throw e
            }
        }

        return {
            city: (ip: string) => {
                if (typeof ip !== 'string') {
                    return null
                }

                let newGeoipResult: City | null = null
                let oldGeoipResult: City | null = null

                try {
                    if (this.config.MMDB_COMPARE_MODE) {
                        oldGeoipResult = hub.mmdb?.city(ip) ?? null
                    }
                } catch {}

                try {
                    if (mmdb) {
                        newGeoipResult = mmdb.city(ip)
                    }
                } catch {}

                if (this.config.MMDB_COMPARE_MODE) {
                    if (oldGeoipResult?.city?.geonameId !== newGeoipResult?.city?.geonameId) {
                        status.warn('🌎', 'New GeoIP result was different', {
                            ip,
                            oldGeoipResult: JSON.stringify(oldGeoipResult?.city),
                            newGeoipResult: JSON.stringify(newGeoipResult?.city),
                        })
                        geoipCompareCounter.inc({ result: 'different' })
                    } else {
                        geoipCompareCounter.inc({ result: 'same' })
                    }
                }

                return oldGeoipResult ? oldGeoipResult : newGeoipResult
            },
        }
    }
}
