import { City, Reader, ReaderModel } from '@maxmind/geoip2-node'
import fs from 'fs/promises'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { PluginsServerConfig } from '../types'
import { isTestEnv } from './env-utils'
import { parseJSON } from './json-parse'
import { logger } from './logger'

export type GeoIp = {
    city: (ip: string) => City | null
}

const geoipLoadCounter = new Counter({
    name: 'cdp_geoip_load_count',
    help: 'Number of times we load the MMDB file',
    labelNames: ['reason'],
})

const geoipBackgroundRefreshCounter = new Counter({
    name: 'cdp_geoip_background_refresh_count',
    help: 'Number of times we tried to refresh the MMDB file',
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
        logger.info('🌎', 'GeoIPService created')
        // NOTE: We typically clean these up in a shutdown task but this isn't necessary anymore as the server shutdown cancels all scheduled jobs
        // We should rely on that instead
        if (!isTestEnv()) {
            schedule.scheduleJob('0 * * * *', () => this.backgroundRefreshMmdb())
        }
    }

    private ensureMmdbLoaded() {
        // This is a lazy getter. If we don't have mmdb or the loading promise then we need to load it
        if (!this._initialMmdbPromise) {
            this._initialMmdbPromise = this.loadMmdb('initial')
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

    private async loadMmdb(reason: string): Promise<ReaderModel> {
        logger.info('🌎', 'Loading MMDB from disk...', {
            location: this.config.MMDB_FILE_LOCATION,
        })

        try {
            geoipLoadCounter.inc({ reason })
            return await instrumentFn(
                {
                    key: 'geoip_load_mmdb',
                    logExecutionTime: true,
                },
                async () => await Reader.open(this.config.MMDB_FILE_LOCATION)
            )
        } catch (e) {
            logger.warn('🌎', 'Loading MMDB from disk failed!', {
                error: e.message,
                location: this.config.MMDB_FILE_LOCATION,
            })
            throw e
        }
    }

    private async loadMmdbMetadata(): Promise<MmdbMetadata | undefined> {
        try {
            return parseJSON(await fs.readFile(this.config.MMDB_FILE_LOCATION.replace('.mmdb', '.json'), 'utf8'))
        } catch (e) {
            logger.warn('🌎', 'Error loading MMDB metadata', {
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
        logger.debug('🌎', 'Checking if we need to refresh the MMDB')
        if (!this._mmdbMetadata) {
            geoipBackgroundRefreshCounter.inc({ result: 'no_metadata' })
            logger.info(
                '🌎',
                'No MMDB metadata found, skipping refresh as this indicates we are not using the S3 MMDB file'
            )
            return
        }

        const metadata = await this.loadMmdbMetadata()

        if (metadata?.date === this._mmdbMetadata.date) {
            geoipBackgroundRefreshCounter.inc({ result: 'up_to_date' })
            logger.debug('🌎', 'MMDB metadata is up to date, skipping refresh')
            return
        }

        logger.info('🌎', 'Refreshing MMDB from disk (s3)')

        geoipBackgroundRefreshCounter.inc({ result: 'refreshing' })
        const mmdb = await this.loadMmdb('background refresh')
        this._mmdb = mmdb
        this._mmdbMetadata = metadata
    }

    async get(): Promise<GeoIp> {
        await this.ensureMmdbLoaded()

        return {
            city: (ip: string) => {
                if (typeof ip !== 'string') {
                    return null
                }

                try {
                    return this._mmdb?.city(ip) ?? null
                } catch {
                    return null
                }
            },
        }
    }
}
