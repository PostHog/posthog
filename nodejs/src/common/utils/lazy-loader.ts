import { Counter, Gauge } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { defaultConfig } from '../config/config'
import { logger } from './logger'
import { sleep } from './utils'

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

/**
 * Retry policy for the loader. When set, a loader call that throws a retriable error
 * (`error.isRetriable === true`) is retried until `maxElapsedMs` is exhausted. Useful for absorbing
 * transient dependency blips (e.g. a Postgres pooler scale-down) so a single failed background load
 * doesn't propagate to every caller — including fire-and-forget ones, where it would crash the process.
 */
export type LoaderRetryOptions = {
    /** Base delay between attempts. */
    retryIntervalMs: number
    /** Random extra delay in `[0, retryJitterMs)` added to each interval to avoid a thundering herd. */
    retryJitterMs?: number
    /** Total time budget for retrying. Once exceeded, the last error is rethrown. */
    maxElapsedMs: number
}

/**
 * Shared retry policy for loaders backed by transient-blip-prone dependencies (e.g. Postgres
 * behind PgBouncer). Sized to ride out a pooler restart without stalling callers for long.
 */
export const DEFAULT_LOADER_RETRY: LoaderRetryOptions = {
    retryIntervalMs: 250,
    retryJitterMs: 250,
    maxElapsedMs: 5000,
}

export type LazyLoaderOptions<T> = {
    name: string
    /** Function to load the values */
    loader: (key: string[]) => Promise<Record<string, T | null | undefined>>
    /** Retry policy for transient loader failures. Off by default (no retry). */
    loaderRetry?: LoaderRetryOptions
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

/**
 * A cached value together with the deadlines that govern it. These live on one object so that
 * writing a value and stamping its deadlines cannot come apart: any code path that sets the
 * value has to produce the deadlines too.
 */
type CacheEntry<T> = {
    value: T | null
    lastUsed: number
    /** Past this, the next lookup reloads before returning. */
    cacheUntil: number
    /** Past this, the next lookup returns the cached value and reloads in the background. */
    backgroundRefreshAfter?: number
}

export class LazyLoader<T> {
    private cache: Record<string, CacheEntry<T> | undefined>
    private pendingLoads: Record<string, Promise<void> | undefined>

    private refreshAgeMs: number
    private refreshNullAgeMs: number
    private refreshBackgroundAgeMs?: number
    private refreshJitterMs: number
    private maxSize: number
    private cacheSize: number = 0

    private buffer:
        | {
              keys: Set<string>
              promise: Promise<void>
          }
        | undefined

    constructor(private readonly options: LazyLoaderOptions<T>) {
        // Keys come from callers and can be ingest tokens or distinct ids, so these maps have no
        // prototype. On a plain object a key like `__proto__` resolves to `Object.prototype`
        // instead of missing, and writing through it mutates a builtin the whole process shares.
        this.cache = Object.create(null)
        this.pendingLoads = Object.create(null)

        this.refreshAgeMs = this.options.refreshAgeMs ?? 1000 * 60 * 5 // 5 minutes
        this.refreshNullAgeMs = this.options.refreshNullAgeMs ?? this.refreshAgeMs
        this.refreshBackgroundAgeMs = this.options.refreshBackgroundAgeMs
        this.refreshJitterMs = this.options.refreshJitterMs ?? this.refreshAgeMs / 5
        this.maxSize = this.options.maxSize ?? defaultConfig.LAZY_LOADER_MAX_SIZE

        if (this.refreshBackgroundAgeMs && this.refreshBackgroundAgeMs > this.refreshAgeMs) {
            throw new Error('refreshBackgroundAgeMs must be smaller than refreshAgeMs')
        }
    }

    /** A snapshot of the cached values. Mutating the result does not affect the cache. */
    public getCache(): Record<string, T | null> {
        const values: Record<string, T | null> = Object.create(null)
        for (const [key, entry] of Object.entries(this.cache)) {
            if (entry) {
                values[key] = entry.value
            }
        }
        return values
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
            const entry = this.cache[k]
            if (entry) {
                // A cacheUntil of 0 forces the next lookup to reload before returning. The
                // background deadline goes with it so the entry never holds two that disagree.
                entry.cacheUntil = 0
                entry.backgroundRefreshAfter = undefined
            }
        }
    }

    public clear(): void {
        this.cache = Object.create(null)
        this.cacheSize = 0
        // this.pendingLoads = {} // NOTE: We don't clear this
        this.updateCacheSizeMetric()
    }

    private setValues(map: LazyLoaderMap<T>): void {
        const now = Date.now()
        const keys = Object.keys(map)
        for (const key of keys) {
            const value = map[key] ?? null
            const jitter = Math.floor(Math.random() * this.refreshJitterMs)
            const refreshAge = value === null ? this.refreshNullAgeMs : this.refreshAgeMs
            const cacheUntil = now + refreshAge + jitter
            // A null takes refreshNullAgeMs for both deadlines, putting them on the same instant,
            // so nulls hard-refresh and never background-refresh.
            const backgroundRefreshAfter = this.refreshBackgroundAgeMs
                ? now + (value === null ? this.refreshNullAgeMs : this.refreshBackgroundAgeMs) + jitter
                : undefined

            if (this.cache[key] === undefined) {
                this.cacheSize++
            }
            this.cache[key] = { value, lastUsed: now, cacheUntil, backgroundRefreshAfter }
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
            // No prototype, for the same reason as the cache: keys are caller-supplied, and this
            // object is handed back to callers who may iterate or spread it.
            const results: Record<string, T | null> = Object.create(null)
            const keysToLoad = new Set<string>()

            // First, check if all keys are already cached and update the lastUsed time
            for (const key of keys) {
                const cached = this.cache[key]

                if (cached !== undefined) {
                    results[key] = cached.value
                    // Always update the lastUsed time
                    cached.lastUsed = Date.now()

                    const cacheUntil = cached.cacheUntil
                    const backgroundRefreshAfter = cached.backgroundRefreshAfter

                    if (Date.now() > cacheUntil) {
                        keysToLoad.add(key)
                        lazyLoaderCacheHits.labels({ name: this.options.name, hit: 'miss' }).inc()
                        continue
                    }

                    // If we haven't triggered a hard refresh, we check for a background refresh
                    if (backgroundRefreshAfter && Date.now() > backgroundRefreshAfter) {
                        void this.load([key]).catch((err) => {
                            logger.warn(`[LazyLoader:${this.options.name}] Background refresh failed`, {
                                key,
                                error: String(err),
                            })
                        })
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
                results[key] = this.cache[key]?.value ?? null
            }

            return results
        })
    }

    /**
     * Schedules the keys to be loaded with a buffer to allow batching multiple keys
     * This is somewhat complex but simplifies the usage around the codebase as you can safely do multiple gets without worrying about firing off duplicate DB requests
     *
     * Loaded values land in `this.cache` via `setValues`; callers read them back from there.
     */
    private async load(keys: string[]): Promise<void> {
        const bufferMs = this.options.bufferMs ?? defaultConfig.LAZY_LOADER_DEFAULT_BUFFER_MS
        const keyPromises: Promise<void>[] = []

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
                    }).then(async (bufferedKeys) => {
                        logger.debug('[LazyLoader]', this.options.name, 'Loading: ', bufferedKeys)
                        this.setValues(await this.invokeLoader(bufferedKeys))
                    }),
                }
                lazyLoaderBufferUsage.labels({ name: this.options.name, hit: 'miss' }).inc()
            } else {
                lazyLoaderBufferUsage.labels({ name: this.options.name, hit: 'hit' }).inc()
            }

            // Add the key to the buffer and add a pendingLoad that waits for the buffer to resolve.
            // The values land in the cache via setValues, so callers read them from there.
            this.buffer.keys.add(key)
            pendingLoad = this.buffer.promise.finally(() => {
                delete this.pendingLoads[key]
            })
            this.pendingLoads[key] = pendingLoad
            keyPromises.push(pendingLoad)
        }

        await Promise.all(keyPromises)
    }

    /**
     * Invoke the loader and normalize its result into a map this class owns: no prototype, an entry
     * for every requested key, and `undefined` collapsed to `null`. Keys the loader returns beyond
     * those requested are kept, so a loader can warm the cache with extras. The loader hands back a
     * plain object, where a key like `__proto__` resolves up the prototype chain instead of reading
     * as absent.
     */
    private async invokeLoader(keys: string[]): Promise<Record<string, T | null>> {
        const loaded = await this.invokeLoaderWithRetry(keys)
        const map: Record<string, T | null> = Object.create(null)
        // A key the loader omits means "no value", not "no answer", so seed every requested key
        // before overlaying what came back.
        for (const key of keys) {
            map[key] = null
        }
        for (const [key, value] of Object.entries(loaded)) {
            map[key] = value ?? null
        }
        return map
    }

    /**
     * Invoke the loader, optionally retrying transient failures.
     *
     * Each attempt re-invokes `loader(keys)` so the ids/tokens are re-evaluated against the source at
     * retry time rather than reusing a stale result. Only retriable errors (`error.isRetriable === true`)
     * are retried; anything else is rethrown immediately so genuine bugs surface rather than being masked.
     */
    private async invokeLoaderWithRetry(keys: string[]): Promise<LazyLoaderMap<T>> {
        const retry = this.options.loaderRetry
        if (!retry) {
            return await this.options.loader(keys)
        }

        const deadline = performance.now() + retry.maxElapsedMs
        let attempt = 0
        for (;;) {
            try {
                return await this.options.loader(keys)
            } catch (error) {
                attempt++
                if (error?.isRetriable !== true) {
                    // Non-transient: rethrow immediately so genuine bugs surface rather than being masked.
                    throw error
                }
                if (performance.now() >= deadline) {
                    logger.warn('🔁', `[LazyLoader:${this.options.name}] Loader retries exhausted, giving up`, {
                        attempt,
                        keys: keys.length,
                        error: String(error),
                    })
                    throw error
                }
                const jitter = retry.retryJitterMs ? Math.floor(Math.random() * retry.retryJitterMs) : 0
                logger.warn('🔁', `[LazyLoader:${this.options.name}] Loader failed, retrying`, {
                    attempt,
                    keys: keys.length,
                    error: String(error),
                })
                await sleep(retry.retryIntervalMs + jitter)
            }
        }
    }

    private evictLRU(): void {
        if (this.cacheSize <= this.maxSize) {
            return
        }

        // Evict extra headroom so we don't re-sort on every subsequent insert.
        // Only apply headroom for caches large enough to benefit (>100 entries).
        const headroom = this.maxSize > 100 ? Math.ceil(this.maxSize * 0.1) : 0
        const toEvict = this.cacheSize - this.maxSize + headroom

        const cacheKeys = Object.keys(this.cache)
        cacheKeys.sort((a, b) => (this.cache[a]?.lastUsed ?? 0) - (this.cache[b]?.lastUsed ?? 0))

        // Evict the least recently used entries
        const evictCount = Math.min(toEvict, cacheKeys.length)
        for (let i = 0; i < evictCount; i++) {
            delete this.cache[cacheKeys[i]]
            this.cacheSize--
        }
    }

    private updateCacheSizeMetric(): void {
        lazyLoaderCacheSize.labels({ name: this.options.name }).set(this.cacheSize)
    }
}
