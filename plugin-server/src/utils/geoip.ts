import { City, Reader, ReaderModel } from '@maxmind/geoip2-node'
import fs from 'fs/promises'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'

import { Hub, PluginsServerConfig } from '../types'
import { isTestEnv } from './env-utils'
import { status } from './status'

export type GeoIp = {
    city: (ip: string) => City | null
}

export const geoipCompareCounter = new Counter({
    name: 'cdp_geoip_compare_count',
    help: 'Number of times we compare the MMDB file to the local file',
    labelNames: ['result'],
})

// This is the shape of the metadata file that we save to S3 whenever we refresh the MMDB file
type MmdbMetadata = {
    date: string
}

export class GeoIPService {
    private _initialMmdbPromise?: Promise<void>
    private _mmdb?: ReaderModel
    private _mmdbMetadata?: MmdbMetadata

    constructor(private config: PluginsServerConfig) {
        status.info('🌎', 'GeoIPService created')
        // NOTE: We typically clean these up in a shutdown task but this isn't necessary anymore as the server shutdown cancels all scheduled jobs
        // We should rely on that instead
        if (!isTestEnv()) {
            schedule.scheduleJob('0 * * * *', () => this.backgroundRefreshMmdb())
        }
    }

    private ensureMmdbLoaded() {
        // This is a lazy getter. If we don't have mmdb or the loading promise then we need to load it
        if (!this._initialMmdbPromise) {
            this._initialMmdbPromise = this.loadMmdb()
                .then((mmdb) => {
                    this._mmdb = mmdb
                    return this.loadMmdbMetadata()
                })
                .then((metadata) => {
                    this._mmdbMetadata = metadata
                })
        }

        return this._initialMmdbPromise
    }

    private async loadMmdb(): Promise<ReaderModel> {
        status.info('🌎', 'Loading MMDB from disk...', {
            location: this.config.MMDB_FILE_LOCATION,
        })

        try {
            return await Reader.open(this.config.MMDB_FILE_LOCATION)
        } catch (e) {
            status.warn('🌎', 'Loading MMDB from disk failed!', {
                error: e.message,
                location: this.config.MMDB_FILE_LOCATION,
            })
            throw e
        }
    }

    private async loadMmdbMetadata(): Promise<MmdbMetadata | undefined> {
        try {
            return JSON.parse(await fs.readFile(this.config.MMDB_FILE_LOCATION.replace('.mmdb', '.json'), 'utf8'))
        } catch (e) {
            status.warn('🌎', 'Error loading MMDB metadata', {
                error: e.message,
                location: this.config.MMDB_FILE_LOCATION,
            })
            // NOTE: For self hosted instances this may fail as it is just using the bundled file so we just ignore the refreshing
            return undefined
        }
    }

    /**
     * This is called every hour to check if we need to refresh the MMDB file.
     * To reduce load we check the metadata file first
     */
    private async backgroundRefreshMmdb(): Promise<void> {
        status.debug('🌎', 'Checking if we need to refresh the MMDB')
        if (!this._mmdbMetadata) {
            status.info(
                '🌎',
                'No MMDB metadata found, skipping refresh as this indicates we are not using the S3 MMDB file'
            )
            return
        }

        const metadata = await this.loadMmdbMetadata()

        if (metadata?.date === this._mmdbMetadata.date) {
            status.debug('🌎', 'MMDB metadata is up to date, skipping refresh')
            return
        }

        status.info('🌎', 'Refreshing MMDB from disk (s3)')

        const mmdb = await this.loadMmdb()
        this._mmdb = mmdb
        this._mmdbMetadata = metadata
    }

    async get(hub: Hub): Promise<GeoIp> {
        // NOTE: There is a lot of code here just testing that the values are the same as before.
        // Once released we don't need the Hub and can simplify this.
        try {
            await this.ensureMmdbLoaded()
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
                    newGeoipResult = this._mmdb?.city(ip) ?? null
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
