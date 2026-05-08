/**
 * Internal data-fetching hook scoped to TaxonomicFilter.
 *
 * Shaped intentionally like `@tanstack/react-query`'s `useQuery` so we can
 * swap to TanStack later without touching call-sites:
 *
 *   const { data, isLoading, isFetching, error, refetch } = useTaxonomicResource(
 *       ['event_definitions', search, offset],
 *       ({ signal }) => fetchEventDefinitions(search, offset, { signal }),
 *       { staleTime: 60_000, keepPreviousData: true }
 *   )
 *
 * Behaviour mirrors react-query semantics for: cache key shape, staleTime,
 * keepPreviousData, dedup of in-flight identical requests, AbortController
 * propagation, and refetch().
 *
 * Differences from react-query (intentionally minimal):
 *   - No retries, no suspense, no infinite queries (we paginate via key).
 *   - No global QueryClient or React context — single module-scoped cache.
 *   - No background refetch on window focus / interval.
 *
 * If we need any of those, swap `useTaxonomicResource` for `useQuery` from
 * `@tanstack/react-query`. The signatures are call-compatible.
 */
import { useEffect, useRef, useSyncExternalStore } from 'react'

export interface UseTaxonomicResourceOptions {
    /** Disable execution. Defaults to true. */
    enabled?: boolean
    /** Time in ms during which a cached entry is considered fresh and not re-fetched. Default 60_000. */
    staleTime?: number
    /** When the key changes, return the previous data while the new request is in flight. Default true. */
    keepPreviousData?: boolean
}

export interface UseTaxonomicResourceResult<T> {
    data: T | undefined
    isLoading: boolean
    isFetching: boolean
    error: unknown
    refetch: () => Promise<T | undefined>
}

export type ResourceQueryFn<T> = (ctx: { signal: AbortSignal }) => Promise<T>

const DEFAULT_STALE_TIME = 60_000

interface CacheEntry {
    data: unknown
    error: unknown
    /** ms timestamp of last successful resolution. 0 if no data yet. */
    ts: number
    /** in-flight request, deduped across consumers. undefined when settled. */
    inflight?: Promise<unknown>
    /** abort controller for the in-flight request. */
    abort?: AbortController
    /** subscribers to notify on entry change. */
    subscribers: Set<() => void>
}

const cache = new Map<string, CacheEntry>()

function hashKey(key: ReadonlyArray<unknown>): string {
    // Stable JSON for deterministic cache keys. Object key order matters here —
    // callers should pass arrays of primitives or objects with stable shape.
    return JSON.stringify(key)
}

function getEntry(hash: string): CacheEntry {
    let entry = cache.get(hash)
    if (!entry) {
        entry = { data: undefined, error: undefined, ts: 0, subscribers: new Set() }
        cache.set(hash, entry)
    }
    return entry
}

function notify(entry: CacheEntry): void {
    for (const sub of entry.subscribers) {
        sub()
    }
}

function isFresh(entry: CacheEntry, staleTime: number): boolean {
    return entry.ts > 0 && Date.now() - entry.ts < staleTime
}

function execute<T>(hash: string, fn: ResourceQueryFn<T>): Promise<T> {
    const entry = getEntry(hash)
    if (entry.inflight) {
        return entry.inflight as Promise<T>
    }
    const abort = new AbortController()
    entry.abort = abort
    entry.error = undefined
    const promise = (async () => {
        try {
            const data = await fn({ signal: abort.signal })
            // If a newer execute() replaced our controller, ignore stale resolve.
            if (entry.abort !== abort) {
                return data
            }
            entry.data = data
            entry.error = undefined
            entry.ts = Date.now()
            entry.inflight = undefined
            entry.abort = undefined
            notify(entry)
            return data
        } catch (err) {
            if (entry.abort !== abort) {
                throw err
            }
            entry.error = err
            entry.inflight = undefined
            entry.abort = undefined
            notify(entry)
            throw err
        }
    })()
    entry.inflight = promise as Promise<unknown>
    return promise
}

export function useTaxonomicResource<T>(
    key: ReadonlyArray<unknown>,
    fn: ResourceQueryFn<T>,
    opts: UseTaxonomicResourceOptions = {}
): UseTaxonomicResourceResult<T> {
    const { enabled = true, staleTime = DEFAULT_STALE_TIME, keepPreviousData = true } = opts
    const hash = hashKey(key)
    const entry = getEntry(hash)

    // Capture latest fn in a ref so we don't trigger refetches when fn identity changes.
    const fnRef = useRef(fn)
    fnRef.current = fn

    // Subscribe to cache entry changes.
    useSyncExternalStore(
        (notifyChange) => {
            entry.subscribers.add(notifyChange)
            return () => {
                entry.subscribers.delete(notifyChange)
                if (entry.subscribers.size === 0) {
                    // Abort any in-flight request the last consumer cared
                    // about — without subscribers, no one's listening to
                    // the result anyway.
                    entry.abort?.abort()
                    // Drop the entry once it's settled and unobserved.
                    // Otherwise long-lived sessions with many distinct
                    // search queries (each its own hash) leak `data` for
                    // the lifetime of the page. Re-mount with the same
                    // key just re-fetches; the cost is bounded by
                    // `staleTime` UX rather than permanent memory growth.
                    if (!entry.inflight) {
                        cache.delete(hash)
                    }
                }
            }
        },
        () => entry.ts + ':' + (entry.error ? 'e' : 'd') + ':' + (entry.inflight ? '1' : '0'),
        () => '0:d:0'
    )

    // Track previous data for keepPreviousData behaviour.
    const previousDataRef = useRef<T | undefined>(undefined)
    if (entry.data !== undefined) {
        previousDataRef.current = entry.data as T
    }

    // Track which hash this hook instance has already kicked off a fetch for.
    // Without this, after a successful resolve the entry.ts change re-fires
    // the effect under `staleTime: 0`, looping forever.
    const lastFiredHashRef = useRef<string | null>(null)

    // Kick off the fetch in an effect (mutating the cache during render breaks
    // useSyncExternalStore — the snapshot would change between render and
    // commit, causing tearing). dedup via entry.inflight makes this idempotent
    // across StrictMode double-mount and concurrent consumers.
    useEffect(() => {
        if (!enabled) {
            return
        }
        // We've already fired for this (instance, hash) and a resolve has happened.
        // Don't auto-refire — let the consumer call refetch() or remount.
        if (lastFiredHashRef.current === hash && entry.ts > 0) {
            return
        }
        if (entry.inflight || entry.error !== undefined) {
            return
        }
        if (isFresh(entry, staleTime)) {
            lastFiredHashRef.current = hash
            return
        }
        lastFiredHashRef.current = hash
        execute(hash, fnRef.current).catch(() => {})
        // Re-run when the key changes or staleness markers move (entry.ts after
        // resolve/invalidate, entry.inflight, entry.error).
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [hash, enabled, staleTime, entry.ts, entry.inflight, entry.error])

    // Fold the "we're about to fetch (effect hasn't run yet)" state into
    // isLoading/isFetching so consumers see a stable busy flag from the very
    // first render, matching react-query's useQuery semantics. Errors halt
    // auto-fetch — consumers must call refetch() to retry. Mirrors react-query's
    // default behaviour (no automatic retry on error).
    const willFetch = enabled && !isFresh(entry, staleTime) && !entry.inflight && entry.error === undefined
    const isLoading = enabled && entry.data === undefined && (entry.inflight !== undefined || willFetch)
    const isFetching = enabled && (entry.inflight !== undefined || willFetch)

    let data: T | undefined = entry.data as T | undefined
    if (data === undefined && keepPreviousData) {
        data = previousDataRef.current
    }

    const refetch = async (): Promise<T | undefined> => {
        try {
            return await execute<T>(hash, fnRef.current)
        } catch {
            return undefined
        }
    }

    return { data, isLoading, isFetching, error: entry.error, refetch }
}

/** Test/utility: clear the entire cache. Not exported in production code paths. */
export function __clearTaxonomicResourceCache(): void {
    for (const entry of cache.values()) {
        entry.abort?.abort()
    }
    cache.clear()
}

/** Imperatively invalidate (mark stale) a single key. Clears any prior error. */
export function invalidateTaxonomicResource(key: ReadonlyArray<unknown>): void {
    const entry = cache.get(hashKey(key))
    if (entry) {
        entry.ts = 0
        entry.error = undefined
        notify(entry)
    }
}

/** Subscribe to a key without rendering. Returns an unsubscribe fn. */
export function subscribeTaxonomicResource(key: ReadonlyArray<unknown>, listener: () => void): () => void {
    const entry = getEntry(hashKey(key))
    entry.subscribers.add(listener)
    return () => {
        entry.subscribers.delete(listener)
    }
}

/** Synchronously read the current cached value (or undefined). For DevTools/debugging. */
export function peekTaxonomicResource<T>(key: ReadonlyArray<unknown>): T | undefined {
    return cache.get(hashKey(key))?.data as T | undefined
}
