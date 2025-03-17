import { Counter } from 'prom-client'

import { logger } from './logger'

const REFRESH_AGE = 1000 * 60 * 5 // 5 minutes
const REFRESH_JITTER_MS = 1000 * 60 // 1 minute

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
    refreshAge?: number
    /** How long to cache null values */
    refreshNullAge?: number
    /** How much jitter to add to the refresh time */
    refreshJitterMs?: number
    /** How long to buffer loads for */
    bufferMs?: number
}

type LazyLoaderMap<T> = Record<string, T | null | undefined>

export class LazyLoader<T> {
    public readonly cache: LazyLoaderMap<T>
    private lastUsed: Record<string, number | undefined>
    private cacheUntil: Record<string, number | undefined>
    private pendingLoads: Record<string, Promise<T | null> | undefined>

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
        this.pendingLoads = {}
    }

    /**
     * Schedules the keys to be loaded with a buffer to allow batching multiple keys
     * This is somewhat complex but simplifies the usage around the codebase as you can safely do multiple gets without worrying about firing off duplicate DB requests
     */
    private async scheduleLoad(keys: string[]): Promise<LazyLoaderMap<T>> {
        const bufferMs = this.options.bufferMs ?? 100
        const keyPromises: Promise<T | null>[] = []

        for (const key of keys) {
            if (this.pendingLoads[key]) {
                // If we already have a scheduled loader for this key we just add it to the list
                keyPromises.push(this.pendingLoads[key])
                continue
            }

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
                    }).then((keys) => {
                        // Pull out the keys to load and clear the buffer
                        logger.info('[LazyLoader]', this.options.name, 'Loading: ', keys)
                        return this.options.loader(keys)
                    }),
                }
            }

            // Add the key to the buffer and add a pendingLoad that waits for the buffer to resolve
            // and then picks out its value
            this.buffer.keys.add(key)
            this.pendingLoads[key] = this.buffer.promise
                .then((map) => map[key] ?? null)
                .finally(() => {
                    delete this.pendingLoads[key]
                })

            keyPromises.push(this.pendingLoads[key])
        }

        const results = await Promise.all(keyPromises)

        return keys.reduce((acc, key, index) => {
            acc[key] = results[index] ?? null
            return acc
        }, {} as LazyLoaderMap<T>)
    }

    /**
     * Ensure that a range of values are preloaded and cached.
     *
     * If already cached, the lastUsed value is updated to now
     * If not cached, the value is loaded as part of the batch and added to the cache.
     * If the value is older than the refreshAge, it is loaded from the database.
     */
    public async load(keys: string[]): Promise<Record<string, T | null>> {
        const results: Record<string, T | null> = {}

        const {
            refreshAge = REFRESH_AGE,
            refreshNullAge = REFRESH_AGE,
            refreshJitterMs = REFRESH_JITTER_MS,
        } = this.options
        const keysToLoad = new Set<string>()

        // First, check if all keys are already cached and update the lastUsed time
        for (const key of keys) {
            const cached = this.cache[key]

            if (cached !== undefined) {
                results[key] = cached
                // Always update the lastUsed time
                this.lastUsed[key] = Date.now()

                const cacheUntil = this.cacheUntil[key] ?? 0

                if (Date.now() > cacheUntil) {
                    keysToLoad.add(key)
                    lazyLoaderCacheHits.labels({ name: this.options.name, hit: 'miss' }).inc()
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

        const loaded = await this.scheduleLoad(Array.from(keysToLoad))

        for (const key of keysToLoad) {
            results[key] = this.cache[key] = loaded[key] ?? null
            this.cacheUntil[key] =
                Date.now() +
                (loaded[key] === null ? refreshNullAge : refreshAge) +
                Math.floor(Math.random() * refreshJitterMs)
            this.lastUsed[key] = Date.now()
        }

        return results
    }

    public async get(key: string): Promise<T | null> {
        const loaded = await this.load([key])

        return loaded[key] ?? null
    }

    public async getMany(keys: string[]): Promise<Record<string, T | null>> {
        return await this.load(keys)
    }

    public markForRefresh(key: string | string[]): void {
        for (const k of Array.isArray(key) ? key : [key]) {
            delete this.cacheUntil[k]
        }
    }
}
