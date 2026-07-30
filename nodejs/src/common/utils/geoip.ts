import { City, Reader, ReaderModel } from '@maxmind/geoip2-node'
import fs from 'fs/promises'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { isTestEnv } from './env-utils'
import { parseJSON } from './json-parse'
import { logger } from './logger'

export type GeoIp = {
    city: (ip: string) => City | null
}

// Hard deadline for MMDB reads. The file lives on an S3-backed FUSE mount, where a wedged
// mountpoint process makes reads hang forever without erroring — which blocked server
// startup indefinitely, as the initial load is awaited before the health server comes up.
export const MMDB_LOAD_TIMEOUT_MS = 60_000

export class MmdbLoadTimeoutError extends Error {
    constructor(location: string) {
        super(`Timed out reading MMDB from disk after ${MMDB_LOAD_TIMEOUT_MS}ms: ${location}`)
        this.name = 'MmdbLoadTimeoutError'
    }
}

function withMmdbLoadTimeout<T>(promise: Promise<T>, location: string): Promise<T> {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new MmdbLoadTimeoutError(location)), MMDB_LOAD_TIMEOUT_MS)
        promise.then(
            (value) => {
                clearTimeout(timer)
                resolve(value)
            },
            (error) => {
                clearTimeout(timer)
                reject(error)
            }
        )
    })
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
    private _mmdbMetadataTimedOut = false

    constructor(private mmdbFileLocation: string) {
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
                    if (mmdb) {
                        return this.loadMmdbMetadata()
                    }
                    return undefined
                })
                .then((metadata) => {
                    this._mmdbMetadata = metadata
                })
        }

        return this._initialMmdbPromise
    }

    private async loadMmdb(reason: string): Promise<ReaderModel | undefined> {
        logger.info('🌎', 'Loading MMDB from disk...', {
            location: this.mmdbFileLocation,
        })

        try {
            geoipLoadCounter.inc({ reason })
            return await instrumentFn(
                {
                    key: 'geoip_load_mmdb',
                    logExecutionTime: true,
                },
                async () => await withMmdbLoadTimeout(Reader.open(this.mmdbFileLocation), this.mmdbFileLocation)
            )
        } catch (e) {
            if (e instanceof MmdbLoadTimeoutError) {
                // A missing or corrupt file means GeoIP is intentionally unavailable (e.g. self-hosted),
                // but a hung read means the mount is broken. Rethrow so the initial load fails startup
                // and the pod gets rescheduled; the background refresh catches this and keeps the
                // already-loaded database.
                logger.error('🌎', 'Loading MMDB from disk timed out', { location: this.mmdbFileLocation })
                throw e
            }
            logger.warn('🌎', 'Loading MMDB from disk failed, GeoIP lookups will be disabled', {
                error: e.message,
                location: this.mmdbFileLocation,
            })
            return undefined
        }
    }

    private async loadMmdbMetadata(): Promise<MmdbMetadata | undefined> {
        const metadataLocation = this.mmdbFileLocation.replace('.mmdb', '.json')
        try {
            const metadata = parseJSON(
                await withMmdbLoadTimeout(fs.readFile(metadataLocation, 'utf8'), metadataLocation)
            )
            this._mmdbMetadataTimedOut = false
            return metadata
        } catch (e) {
            // A timed-out read means the mount is unhealthy, not that the metadata file doesn't
            // exist — remember it so the background refresh retries instead of assuming self-hosted.
            this._mmdbMetadataTimedOut = e instanceof MmdbLoadTimeoutError
            logger.warn('🌎', 'Error loading MMDB metadata', {
                error: e.message,
                location: this.mmdbFileLocation,
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
        if (!this._mmdbMetadata && !this._mmdbMetadataTimedOut) {
            geoipBackgroundRefreshCounter.inc({ result: 'no_metadata' })
            logger.info(
                '🌎',
                'No MMDB metadata found, skipping refresh as this indicates we are not using the S3 MMDB file'
            )
            return
        }

        const metadata = await this.loadMmdbMetadata()

        if (!metadata) {
            geoipBackgroundRefreshCounter.inc({ result: 'no_metadata' })
            return
        }

        if (metadata.date === this._mmdbMetadata?.date) {
            geoipBackgroundRefreshCounter.inc({ result: 'up_to_date' })
            logger.debug('🌎', 'MMDB metadata is up to date, skipping refresh')
            return
        }

        logger.info('🌎', 'Refreshing MMDB from disk (s3)')

        geoipBackgroundRefreshCounter.inc({ result: 'refreshing' })
        // We already have a working database at this point, so a failed or timed-out
        // reload must never take the service down — keep serving the current one.
        const mmdb = await this.loadMmdb('background refresh').catch(() => undefined)
        if (mmdb) {
            this._mmdb = mmdb
            this._mmdbMetadata = metadata
        } else {
            logger.warn('🌎', 'Background MMDB refresh failed, keeping existing MMDB')
        }
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
