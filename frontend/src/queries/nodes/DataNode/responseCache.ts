import { getContext } from 'kea'

import { AnyResponseType } from '~/queries/schema/schema-general'

import type { DataNodeLogicProps } from './dataNodeLogic'

const MAX_ENTRIES = 200
const MAX_ENTRY_LENGTH = 2_000_000
// Bounds memory by serialized size, so a notebook of large tables can't retain an unbounded amount.
const MAX_TOTAL_LENGTH = 20_000_000
export const RESPONSE_CACHE_TTL = 10 * 60 * 1000

type Entry = { response: AnyResponseType; expiresAt: number; length: number }
type ResponseCache = {
    entries: Map<string, Entry>
    totalLength: number
    inflight: Map<string, Promise<AnyResponseType | null>>
}
const caches = new WeakMap<ReturnType<typeof getContext>, ResponseCache>()

export function responseCacheKey(
    props: DataNodeLogicProps,
    userId: number | undefined,
    teamId: number | null
): string | null {
    return props.retainResponseOnUnmount && !props.doNotLoad && !props.refresh?.startsWith('force_') && userId && teamId
        ? JSON.stringify([
              userId,
              teamId,
              props.key,
              props.query,
              props.filtersOverride,
              props.variablesOverride,
              props.modifiers,
              props.limitContext,
          ])
        : null
}

export function isCompleteResponse(response: AnyResponseType | null | undefined): response is AnyResponseType {
    return (
        !!response &&
        !('error' in response && response.error) &&
        response.query_status?.complete !== false &&
        (('result' in response && response.result != null) || ('results' in response && response.results != null))
    )
}

function getCache(): ResponseCache {
    const context = getContext()
    let cache = caches.get(context)
    if (!cache) {
        cache = { entries: new Map(), totalLength: 0, inflight: new Map() }
        caches.set(context, cache)
    }
    return cache
}

function deleteEntry(cache: ResponseCache, key: string): void {
    const entry = cache.entries.get(key)
    if (entry) {
        cache.totalLength -= entry.length
        cache.entries.delete(key)
    }
}

export function getRetainedResponse(key: string | null): AnyResponseType | null {
    if (!key) {
        return null
    }
    const cache = getCache()
    const entry = cache.entries.get(key)
    if (!entry || entry.expiresAt <= Date.now()) {
        deleteEntry(cache, key)
        return null
    }
    cache.entries.delete(key)
    cache.entries.set(key, entry)
    return structuredClone(entry.response)
}

export function forgetRetainedResponse(key: string | null): void {
    if (key) {
        deleteEntry(getCache(), key)
    }
}

export function retainResponse(key: string | null, response: AnyResponseType | null | undefined): void {
    retainInto(getCache(), key, response)
}

function retainInto(cache: ResponseCache, key: string | null, response: AnyResponseType | null | undefined): void {
    if (!key || !isCompleteResponse(response)) {
        return
    }
    const serialized = JSON.stringify(response)
    if (serialized.length > MAX_ENTRY_LENGTH) {
        return
    }
    deleteEntry(cache, key)
    cache.entries.set(key, {
        response: JSON.parse(serialized),
        expiresAt: Date.now() + RESPONSE_CACHE_TTL,
        length: serialized.length,
    })
    cache.totalLength += serialized.length
    while (cache.entries.size > MAX_ENTRIES || cache.totalLength > MAX_TOTAL_LENGTH) {
        deleteEntry(cache, cache.entries.keys().next().value!)
    }
}

export function getInflightResponse(key: string | null): Promise<AnyResponseType | null> | null {
    return key ? (getCache().inflight.get(key) ?? null) : null
}

/**
 * Lets a query outlive the data node that started it. A node that remounts with the same key awaits
 * the running request instead of cancelling it and starting over, and the result is retained.
 */
export function trackInflightResponse(key: string | null, promise: Promise<AnyResponseType | null>): void {
    if (!key) {
        return
    }
    const cache = getCache()
    const { inflight } = cache
    inflight.set(key, promise)
    promise
        .then((response) => retainInto(cache, key, response))
        .catch(() => {})
        .finally(() => {
            if (inflight.get(key) === promise) {
                inflight.delete(key)
            }
        })
}
