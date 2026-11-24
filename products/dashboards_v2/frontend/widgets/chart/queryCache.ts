import type { DataFrame, RunQuery, WidgetQuery } from './vizTypes'

type Entry = { promise: Promise<DataFrame[]>; frames?: DataFrame[] }

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

/** The frames a query already returned through this runner, or undefined when it has not finished. */
export function cachedFrames(runQuery: RunQuery, queryKey: string): DataFrame[] | undefined {
    return caches.get(runQuery)?.get(queryKey)?.frames
}

/**
 * Runs a query once per runner, so a tile that scrolls out of view and back reuses the result, or the request still
 * in flight, instead of running it again. A failed query is dropped, so the next mount tries again.
 */
export function runCachedQuery(runQuery: RunQuery, queryKey: string): Promise<DataFrame[]> {
    const cache = cacheFor(runQuery)
    const existing = cache.get(queryKey)
    if (existing) {
        return existing.promise
    }
    // A runner that throws before it returns a promise still ends in a rejected promise.
    const promise = Promise.resolve().then(() => runQuery(JSON.parse(queryKey) as WidgetQuery))
    const entry: Entry = { promise }
    cache.set(queryKey, entry)
    promise.then(
        (frames) => {
            entry.frames = frames
        },
        () => {
            if (cache.get(queryKey) === entry) {
                cache.delete(queryKey)
            }
        }
    )
    return promise
}
