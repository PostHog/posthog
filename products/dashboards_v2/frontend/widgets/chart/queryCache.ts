import type { QueryRequest, QueryResult, RunQuery } from './vizTypes'

type Entry = { promise: Promise<QueryResult>; result?: QueryResult }

// Enough for every tile on a large dashboard, while each query edit adds a key, so the oldest results go first.
export const MAX_CACHED_QUERIES = 200

// Kept per runner, so a host that wants fresh results passes a new runner and the old results go with the old one.
const caches = new WeakMap<RunQuery, Map<string, Entry>>()

function cacheFor(runQuery: RunQuery): Map<string, Entry> {
    let cache = caches.get(runQuery)
    if (!cache) {
        cache = new Map()
        caches.set(runQuery, cache)
    }
    return cache
}

/** The result a query already returned through this runner, or undefined when it has not finished. */
export function cachedResult(runQuery: RunQuery, queryKey: string): QueryResult | undefined {
    return caches.get(runQuery)?.get(queryKey)?.result
}

/**
 * Runs a query once per runner, so a tile that scrolls out of view and back reuses the result, or the request still
 * in flight, instead of running it again. A failed query is dropped, so the next mount tries again.
 */
export function runCachedQuery(runQuery: RunQuery, queryKey: string): Promise<QueryResult> {
    const cache = cacheFor(runQuery)
    const existing = cache.get(queryKey)
    if (existing) {
        // A Map keeps insertion order, so moving the entry to the end marks it as the most recently used.
        cache.delete(queryKey)
        cache.set(queryKey, existing)
        return existing.promise
    }
    // A runner that throws before it returns a promise still ends in a rejected promise.
    const promise = Promise.resolve().then(() => runQuery(JSON.parse(queryKey) as QueryRequest))
    const entry: Entry = { promise }
    cache.set(queryKey, entry)
    if (cache.size > MAX_CACHED_QUERIES) {
        cache.delete(cache.keys().next().value as string)
    }
    promise.then(
        (result) => {
            entry.result = result
        },
        () => {
            if (cache.get(queryKey) === entry) {
                cache.delete(queryKey)
            }
        }
    )
    return promise
}
