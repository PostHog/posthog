import { City, Reader, ReaderModel } from '@maxmind/geoip2-node'
import fs from 'fs/promises'
import { DateTime } from 'luxon'
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
    private _lastRefreshDate: string | undefined

    constructor(private config: PluginsServerConfig) {}

    private getMmdb() {
        if (!this._mmdbPromise) {
            this._mmdbPromise = this.refreshMmdbIfNeeded()
        }

        return this._mmdbPromise
    }

    private async refreshMmdbIfNeeded(): Promise<ReaderModel> {
        status.info('🌎', 'Refreshing MMDB')
        /**
         * NOTE: We sync the MMDB files to S3 in posthog-cloud-infra along with a JSON file that contains the date of the last refresh.
         * That way we can do a cheap check to see if we need to refresh the MMDB file rather than downloading the whole file every time.
         */
        try {
            const metadata: { date: string } = JSON.parse(
                await fs.readFile(this.config.MMDB_FILE_LOCATION.replace('.mmdb', '.json'), 'utf8')
            )

            // If the date is different and we have a promise then we can return the promise
            if (metadata.date === this._lastRefreshDate && this._mmdbPromise) {
                return this._mmdbPromise
            }

            // Otherwise we can update the last refresh date and load the new file
            this._lastRefreshDate = metadata.date
        } catch (e) {
            // NOTE: For self hosted instances this may fail as it is just using the bundled file so we just ignore the refreshing
        }

        status.info('🌎', 'Refreshing MMDB from disk (s3)')
        return Reader.open(this.config.MMDB_FILE_LOCATION)
            .then((mmdb) => {
                status.info('🌎', 'Refreshed MMDB from disk (s3)!')
                return mmdb
            })
            .catch((e) => {
                status.warn('🌎', 'Error getting MMDB', {
                    error: e.message,
                })
                throw e
            })
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
