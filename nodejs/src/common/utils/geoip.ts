import { City, Reader, ReaderModel } from '@maxmind/geoip2-node'
import fs from 'fs/promises'
import * as schedule from 'node-schedule'
import { Counter, Gauge } from 'prom-client'

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

const geoipFallbackInUseGauge = new Gauge({
    name: 'cdp_geoip_fallback_in_use',
    help: 'Whether lookups are served by the fallback MMDB bundled in the image (1) instead of the configured one (0)',
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
    private _loadedFileLocation?: string
    private _usingFallback = false

    constructor(
        private mmdbFileLocation: string,
        private fallbackMmdbFileLocation?: string
    ) {
        logger.info('🌎', 'GeoIPService created')
        // NOTE: We typically clean these up in a shutdown task but this isn't necessary anymore as the server shutdown cancels all scheduled jobs
        // We should rely on that instead
        if (!isTestEnv()) {
            schedule.scheduleJob('0 * * * *', () => this.backgroundRefreshMmdb())
        }
    }

    /**
     * Where the serving database was read from, or undefined if there is none. This is the fallback
     * location while the configured one is unreadable, so anything else that opens the same file
     * (the Rust VM's own reader) can avoid the broken mount too.
     */
    get loadedFileLocation(): string | undefined {
        return this._loadedFileLocation
    }

    private ensureMmdbLoaded() {
        // This is a lazy getter. If we don't have mmdb or the loading promise then we need to load it
        if (!this._initialMmdbPromise) {
            this._initialMmdbPromise = this.loadInitialMmdb()
        }

        return this._initialMmdbPromise
    }

    private async loadInitialMmdb(): Promise<void> {
        let mmdb: ReaderModel | undefined
        let loadError: unknown

        try {
            mmdb = await this.loadMmdb('initial', this.mmdbFileLocation)
        } catch (e) {
            loadError = e
        }

        if (mmdb) {
            this.setMmdb(mmdb, this.mmdbFileLocation, false)
            this._mmdbMetadata = await this.loadMmdbMetadata()
            return
        }

        const fallbackMmdb = await this.loadFallbackMmdb()
        if (fallbackMmdb) {
            // The database bundled in the image is as old as the image, so this trades a little
            // staleness for staying up. The background refresh keeps retrying the configured
            // location, so a pod moves back on its own once that file is readable again.
            this.setMmdb(fallbackMmdb, this.fallbackMmdbFileLocation!, true)
            logger.warn('🌎', 'Serving GeoIP lookups from the fallback MMDB, which may be stale', {
                location: this.mmdbFileLocation,
                fallbackLocation: this.fallbackMmdbFileLocation,
            })
            return
        }

        if (loadError) {
            // A hung read means the mount is broken and we have nothing to serve from. Rethrow so
            // the initial load fails startup and the pod gets rescheduled.
            throw loadError
        }

        logger.warn('🌎', 'No MMDB could be loaded, GeoIP lookups will be disabled', {
            location: this.mmdbFileLocation,
        })
    }

    private setMmdb(mmdb: ReaderModel, location: string, usingFallback: boolean): void {
        this._mmdb = mmdb
        this._loadedFileLocation = location
        this._usingFallback = usingFallback
        geoipFallbackInUseGauge.set(usingFallback ? 1 : 0)
    }

    private async loadFallbackMmdb(): Promise<ReaderModel | undefined> {
        if (!this.fallbackMmdbFileLocation || this.fallbackMmdbFileLocation === this.mmdbFileLocation) {
            return undefined
        }

        // Never fatal: the fallback exists to keep the service up, so a bad one leaves us exactly
        // where we would have been without it.
        return await this.loadMmdb('fallback', this.fallbackMmdbFileLocation).catch(() => undefined)
    }

    private async loadMmdb(reason: string, location: string): Promise<ReaderModel | undefined> {
        logger.info('🌎', 'Loading MMDB from disk...', {
            location,
        })

        try {
            geoipLoadCounter.inc({ reason })
            return await instrumentFn(
                {
                    key: 'geoip_load_mmdb',
                    logExecutionTime: true,
                },
                async () => await withMmdbLoadTimeout(Reader.open(location), location)
            )
        } catch (e) {
            if (e instanceof MmdbLoadTimeoutError) {
                // A missing or corrupt file means GeoIP is intentionally unavailable (e.g. self-hosted),
                // but a hung read means the mount is broken. Rethrow so the caller can decide: the
                // initial load falls back to the bundled database or fails startup, and the
                // background refresh keeps the already-loaded one.
                logger.error('🌎', 'Loading MMDB from disk timed out', { location })
                throw e
            }
            logger.warn('🌎', 'Loading MMDB from disk failed', {
                error: e.message,
                location,
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
        // Serving the fallback always warrants a retry — that is how a pod gets off it unattended.
        if (!this._mmdbMetadata && !this._mmdbMetadataTimedOut && !this._usingFallback) {
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

        // While on the fallback we reload whatever the date says, since the point is to get back
        // onto the configured file as soon as it is readable.
        if (!this._usingFallback && metadata.date === this._mmdbMetadata?.date) {
            geoipBackgroundRefreshCounter.inc({ result: 'up_to_date' })
            logger.debug('🌎', 'MMDB metadata is up to date, skipping refresh')
            return
        }

        logger.info('🌎', 'Refreshing MMDB from disk (s3)')

        geoipBackgroundRefreshCounter.inc({ result: 'refreshing' })
        // We already have a working database at this point, so a failed or timed-out
        // reload must never take the service down — keep serving the current one.
        const mmdb = await this.loadMmdb('background refresh', this.mmdbFileLocation).catch(() => undefined)
        if (mmdb) {
            this.setMmdb(mmdb, this.mmdbFileLocation, false)
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
