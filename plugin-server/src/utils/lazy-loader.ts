import { Counter, Gauge } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { defaultConfig } from '../config/config'
import { logger } from './logger'

const lazyLoaderCacheHits = new Counter({
    name: 'lazy_loader_cache_hits',
    help: 'The number of times we have hit the cache',
    labelNames: ['name', 'hit'],
})

const lazyLoaderFullCacheHits = new Counter({
    name: 'lazy_loader_full_cache_hits',
    help: 'The number of times we have hit the cache for all keys',
    labelNames: ['name', 'hit'],
})

const lazyLoaderBufferUsage = new Counter({
    name: 'lazy_loader_buffer_usage',
    help: 'The number of times we have used the buffer indicating better batching',
    labelNames: ['name', 'hit'],
})

const lazyLoaderQueuedCacheHits = new Counter({
    name: 'lazy_loader_queued_cache_hits',
    help: 'The number of times we have hit the cached loading promise for a key',
    labelNames: ['name', 'hit'],
})

const lazyLoaderCacheSize = new Gauge({
    name: 'lazy_loader_cache_size',
    help: 'Current number of entries in the cache',
    labelNames: ['name'],
})

/**
 * We have a common pattern across consumers where we want to:
 * - Load a value lazily
 * - Minimize queries to the DB for multiple values (e.g. teams for events)
 * - Keep that value cached ensuring any caller to retrieve it will get the value
 * - "Refresh" the value after a certain age
 * - "Drop" the value after a much longer age
 *
 * Follow up improvements:
 * - Soft and hard refresh times - if soft it can be refreshed in the background, non blocking
 * - Parallel loading defense - multiple calls for the same value in parallel only loads once
 */

export type LazyLoaderOptions<T> = {
    name: string
    /** Function to load the values */
    loader: (key: string[]) => Promise<Record<string, T | null | undefined>>
    /** How long to cache the value */
    refreshAgeMs?: number
    /** How long to cache null values */
    refreshNullAgeMs?: number
    /** How long to cache the value before refreshing in the background - must be smaller than refreshAgeMs */
    refreshBackgroundAgeMs?: number
    /** How much jitter to add to the refresh time */
    refreshJitterMs?: number
    /** How long to buffer loads for - if set to 0 then it will load immediately without buffering */
    bufferMs?: number
    /** Maximum number of entries in the cache - LRU eviction when exceeded */
    maxSize?: number
}

type LazyLoaderMap<T> = Record<string, T | null | undefined>

export class LazyLoader<T> {
    private cache: LazyLoaderMap<T>
    private lastUsed: Record<string, number | undefined>
    private cacheUntil: Record<string, number | undefined>
    private backgroundRefreshAfter: Record<string, number | undefined>
    private pendingLoads: Record<string, Promise<T | null> | undefined>

    private refreshAgeMs: number
    private refreshNullAgeMs: number
    private refreshBackgroundAgeMs?: number
    private refreshJitterMs: number
    private maxSize: number

    private buffer:
        | {
              keys: Set<string>
              promise: Promise<LazyLoaderMap<T>>
          }
        | undefined

    constructor(private readonly options: LazyLoaderOptions<T>) {
        this.cache = {}
        this.lastUsed = {}
        this.cacheUntil = {}
        this.backgroundRefreshAfter = {}
        this.pendingLoads = {}

        this.refreshAgeMs = this.options.refreshAgeMs ?? 1000 * 60 * 5 // 5 minutes
        this.refreshNullAgeMs = this.options.refreshNullAgeMs ?? this.refreshAgeMs
        this.refreshBackgroundAgeMs = this.options.refreshBackgroundAgeMs
        this.refreshJitterMs = this.options.refreshJitterMs ?? this.refreshAgeMs / 5
        this.maxSize = this.options.maxSize ?? defaultConfig.LAZY_LOADER_MAX_SIZE

        if (this.refreshBackgroundAgeMs && this.refreshBackgroundAgeMs > this.refreshAgeMs) {
            throw new Error('refreshBackgroundAgeMs must be smaller than refreshAgeMs')
        }
    }

    public getCache(): LazyLoaderMap<T> {
        return this.cache
    }

    public async get(key: string): Promise<T | null> {
        const loaded = await this.loadViaCache([key])
        return loaded[key] ?? null
    }

    public async getMany(keys: string[]): Promise<Record<string, T | null>> {
        return await this.loadViaCache(keys)
    }

    public markForRefresh(key: string | string[]): void {
        for (const k of Array.isArray(key) ? key : [key]) {
            delete this.cacheUntil[k]
        }
    }

    public clear(): void {
        this.cache = {}
        this.lastUsed = {}
        this.cacheUntil = {}
        this.backgroundRefreshAfter = {}
        // this.pendingLoads = {} // NOTE: We don't clear this
        this.updateCacheSizeMetric()
    }

    private setValues(map: LazyLoaderMap<T>): void {
        for (const [key, value] of Object.entries(map)) {
            this.cache[key] = value ?? null
            // Always update the lastUsed time
            this.lastUsed[key] = Date.now()
            const valueOrNull = value ?? null
            const jitter = Math.floor(Math.random() * this.refreshJitterMs)
            this.cacheUntil[key] =
                Date.now() + (valueOrNull === null ? this.refreshNullAgeMs : this.refreshAgeMs) + jitter

            if (this.refreshBackgroundAgeMs) {
                this.backgroundRefreshAfter[key] =
                    Date.now() + (valueOrNull === null ? this.refreshNullAgeMs : this.refreshBackgroundAgeMs) + jitter
            }
        }
        this.evictLRU()
        this.updateCacheSizeMetric()
    }

    /**
     * Ensure that a range of values are preloaded and cached.
     *
     * If already cached, the lastUsed value is updated to now
     * If not cached, the value is loaded as part of the batch and added to the cache.
     * If the value is older than the refreshAge, it is loaded from the database.
     */
    private async loadViaCache(keys: string[]): Promise<Record<string, T | null>> {
        return await instrumentFn(`lazyLoader.loadViaCache`, async () => {
            const results: Record<string, T | null> = {}
            const keysToLoad = new Set<string>()

            // First, check if all keys are already cached and update the lastUsed time
            for (const key of keys) {
                const cached = this.cache[key]

                if (cached !== undefined) {
                    results[key] = cached
                    // Always update the lastUsed time
                    this.lastUsed[key] = Date.now()

                    const cacheUntil = this.cacheUntil[key] ?? 0
                    const backgroundRefreshAfter = this.backgroundRefreshAfter[key]

                    if (Date.now() > cacheUntil) {
                        keysToLoad.add(key)
                        lazyLoaderCacheHits.labels({ name: this.options.name, hit: 'miss' }).inc()
                        continue
                    }

                    // If we haven't triggered a hard refresh, we check for a background refresh
                    if (backgroundRefreshAfter && Date.now() > backgroundRefreshAfter) {
                        void this.load([key])
                        lazyLoaderCacheHits.labels({ name: this.options.name, hit: 'hit_background' }).inc()
                        continue
                    }
                } else {
                    keysToLoad.add(key)
                    lazyLoaderCacheHits.labels({ name: this.options.name, hit: 'miss' }).inc()
                    continue
                }

                lazyLoaderCacheHits.labels({ name: this.options.name, hit: 'hit' }).inc()
            }

            if (keysToLoad.size === 0) {
                lazyLoaderFullCacheHits.labels({ name: this.options.name, hit: 'hit' }).inc()
                return results
            }

            lazyLoaderFullCacheHits.labels({ name: this.options.name, hit: 'miss' }).inc()

            // We have something to load so we schedule it and then await all of them
            await this.load(Array.from(keysToLoad))

            for (const key of keys) {
                // Grab the new cached result for all keys
                results[key] = this.cache[key] ?? null
            }

            return results
        })
    }

    /**
     * Schedules the keys to be loaded with a buffer to allow batching multiple keys
     * This is somewhat complex but simplifies the usage around the codebase as you can safely do multiple gets without worrying about firing off duplicate DB requests
     */
    private async load(keys: string[]): Promise<LazyLoaderMap<T>> {
        const bufferMs = this.options.bufferMs ?? defaultConfig.LAZY_LOADER_DEFAULT_BUFFER_MS
        const keyPromises: Promise<T | null>[] = []

        for (const key of keys) {
            let pendingLoad = this.pendingLoads[key]
            if (pendingLoad) {
                // If we already have a scheduled loader for this key we just add it to the list
                keyPromises.push(pendingLoad)
                lazyLoaderQueuedCacheHits.labels({ name: this.options.name, hit: 'hit' }).inc()
                continue
            }
            lazyLoaderQueuedCacheHits.labels({ name: this.options.name, hit: 'miss' }).inc()

            if (!this.buffer) {
                // If we don't have a buffer then we create one
                // The buffer is a combination of a set of keys and a promise that will resolve after a setTimeout to then call the loader for those keys
                this.buffer = {
                    keys: new Set(),
                    promise: new Promise<string[]>((resolve) => {
                        setTimeout(() => {
                            const keys = Array.from(this.buffer!.keys)
                            this.buffer = undefined
                            resolve(keys)
                        }, bufferMs)
                    })
                        .then((keys) => {
                            // Pull out the keys to load and clear the buffer
                            logger.debug('[LazyLoader]', this.options.name, 'Loading: ', keys)
                            return this.options.loader(keys)
                        })
                        .then((map) => {
                            this.setValues(map)
                            return map
                        }),
                }
                lazyLoaderBufferUsage.labels({ name: this.options.name, hit: 'miss' }).inc()
            } else {
                lazyLoaderBufferUsage.labels({ name: this.options.name, hit: 'hit' }).inc()
            }

            // Add the key to the buffer and add a pendingLoad that waits for the buffer to resolve
            // and then picks out its value
            this.buffer.keys.add(key)
            pendingLoad = this.buffer.promise
                .then((map) => map[key] ?? null)
                .finally(() => {
                    delete this.pendingLoads[key]
                })
            this.pendingLoads[key] = pendingLoad
            keyPromises.push(pendingLoad)
        }

        const results = await Promise.all(keyPromises)
        const mappedResults = keys.reduce((acc, key, index) => {
            acc[key] = results[index] ?? null
            return acc
        }, {} as LazyLoaderMap<T>)

        this.setValues(mappedResults)

        return mappedResults
    }

    private evictLRU(): void {
        const cacheSize = Object.keys(this.cache).length
        if (cacheSize <= this.maxSize) {
            return
        }

        // Sort keys by lastUsed time (oldest first)
        const sortedKeys = Object.entries(this.lastUsed)
            .filter(([key]) => key in this.cache)
            .sort((a, b) => (a[1] ?? 0) - (b[1] ?? 0))

        // Calculate how many to evict
        const toEvict = cacheSize - this.maxSize
        const keysToEvict = sortedKeys.slice(0, toEvict).map(([key]) => key)

        // Evict the least recently used entries
        for (const key of keysToEvict) {
            delete this.cache[key]
            delete this.lastUsed[key]
            delete this.cacheUntil[key]
            delete this.backgroundRefreshAfter[key]
        }

        if (keysToEvict.length > 0) {
            this.updateCacheSizeMetric()
        }
    }

    private updateCacheSizeMetric(): void {
        const cacheSize = Object.keys(this.cache).length
        lazyLoaderCacheSize.labels({ name: this.options.name }).set(cacheSize)
    }
}
