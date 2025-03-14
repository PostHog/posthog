import { Counter } from 'prom-client'

import { status } from './status'

const REFRESH_AGE = 1000 * 60 * 5 // 5 minutes
const REFRESH_JITTER_MS = 1000 * 60 // 1 minutes

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
 */

export type LazyLoaderOptions<T> = {
    name: string
    /** Function to load the values */
    loader: (key: string[]) => Promise<Record<string, T | undefined>>
    /** How long to cache the value */
    refreshAge?: number
    /** How long to cache null values */
    refreshNullAge?: number
    /** How much jitter to add to the refresh time */
    refreshJitterMs?: number
    /** How long to keep the value in the cache after it's loaded */
    dropAge?: number
    /** Whether to throw an error if the loader function throws an error */
    throwOnLoadError?: boolean
}
export class LazyLoader<T> {
    private cache: Record<string, T | null | undefined>
    private lastUsed: Record<string, number | undefined>
    private cacheUntil: Record<string, number | undefined>

    constructor(private readonly options: LazyLoaderOptions<T>) {
        this.cache = {}
        this.lastUsed = {}
        this.cacheUntil = {}
    }

    /**
     * Ensure that a range of values are preloaded and cached.
     *
     * If already cached, the lastUsed value is updated to now.
     * If not cached, the value is loaded as part of the batch and added to the cache.
     * If the value is older than the refreshAge, it is loaded from the database.
     */
    public async ensureLoaded(keys: string[]): Promise<Record<string, T | null>> {
        const results: Record<string, T | null> = {}

        const now = Date.now()
        const {
            loader,
            refreshAge = REFRESH_AGE,
            refreshNullAge = REFRESH_AGE,
            refreshJitterMs = REFRESH_JITTER_MS,
            throwOnLoadError = true,
        } = this.options
        const keysToLoad = new Set<string>()

        // First, check if all keys are already cached and update the lastUsed time
        for (const key of keys) {
            const cached = this.cache[key]

            if (cached !== undefined) {
                results[key] = cached
                this.lastUsed[key] = now

                const cacheUntil = this.cacheUntil[key] ?? 0

                if (now - cacheUntil > (cached === null ? refreshNullAge : refreshAge)) {
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

        let loaded: Record<string, T | undefined>
        try {
            loaded = await loader(Array.from(keysToLoad))
        } catch (error) {
            if (throwOnLoadError) {
                throw error
            }
            status.error(
                '🍿',
                `[LazyLoader](${this.options.name}) Error loading values but silently ignoring: ${error}`
            )
            loaded = {}
        }
        for (const key of keysToLoad) {
            this.cache[key] = loaded[key] ?? null
            this.cacheUntil[key] = now + Math.floor(Math.random() * refreshJitterMs)
            this.lastUsed[key] = now
        }

        return results
    }

    public async get(key: string): Promise<T | null | undefined> {
        const loaded = await this.ensureLoaded([key])
        return loaded[key]
    }

    public async getMany(keys: string[]): Promise<Record<string, T | null>> {
        return await this.ensureLoaded(keys)
    }

    public markForRefresh(key: string | string[]): void {
        for (const k of Array.isArray(key) ? key : [key]) {
            delete this.cacheUntil[k]
        }
    }
}
