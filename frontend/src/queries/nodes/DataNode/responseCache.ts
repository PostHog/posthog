import { getContext } from 'kea'

import { AnyResponseType } from '~/queries/schema/schema-general'
import type { InsightLogicProps, InsightModel } from '~/types'

import type { DataNodeLogicProps } from './dataNodeLogic'

const MAX_ENTRIES = 100
// Long-range insights often serialize to megabytes, so the cache bounds total size instead of rejecting them.
const MAX_TOTAL_LENGTH = 20_000_000
const MAX_ENTRY_LENGTH = 5_000_000
export const RESPONSE_CACHE_TTL = 15 * 60 * 1000

type Entry = { serialized: string; expiresAt: number }
type Cache = { entries: Map<string, Entry>; totalLength: number }
const caches = new WeakMap<ReturnType<typeof getContext>, Cache>()

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

export function insightCacheKey(
    props: InsightLogicProps,
    userId: number | undefined,
    teamId: number | null
): string | null {
    return props.retainResponseOnUnmount && !props.doNotLoad && props.dashboardItemId && userId && teamId
        ? JSON.stringify([
              'insight',
              userId,
              teamId,
              props.dashboardItemId,
              props.filtersOverride,
              props.variablesOverride,
              props.tileFiltersOverride,
          ])
        : null
}

function getCache(): Cache {
    const context = getContext()
    let cache = caches.get(context)
    if (!cache) {
        cache = { entries: new Map(), totalLength: 0 }
        caches.set(context, cache)
    }
    return cache
}

function forget(cache: Cache, key: string): void {
    const entry = cache.entries.get(key)
    if (entry) {
        cache.entries.delete(key)
        cache.totalLength -= entry.serialized.length
    }
}

function read<T>(key: string | null): T | null {
    if (!key) {
        return null
    }
    const cache = getCache()
    const entry = cache.entries.get(key)
    if (!entry || entry.expiresAt <= Date.now()) {
        forget(cache, key)
        return null
    }
    cache.entries.delete(key)
    cache.entries.set(key, entry)
    return JSON.parse(entry.serialized) as T
}

function write(key: string, value: unknown): void {
    const serialized = JSON.stringify(value)
    const cache = getCache()
    forget(cache, key)
    if (serialized.length > MAX_ENTRY_LENGTH) {
        return
    }
    cache.entries.set(key, { serialized, expiresAt: Date.now() + RESPONSE_CACHE_TTL })
    cache.totalLength += serialized.length
    while (cache.entries.size > MAX_ENTRIES || cache.totalLength > MAX_TOTAL_LENGTH) {
        forget(cache, cache.entries.keys().next().value!)
    }
}

export function getRetainedResponse(key: string | null): AnyResponseType | null {
    return read<AnyResponseType>(key)
}

export function forgetRetainedResponse(key: string | null): void {
    if (key) {
        forget(getCache(), key)
    }
}

export function retainResponse(key: string | null, response: AnyResponseType | null | undefined): void {
    if (key && isCompleteResponse(response)) {
        write(key, response)
    }
}

export function getRetainedInsight(key: string | null): Partial<InsightModel> | null {
    return read<Partial<InsightModel>>(key)
}

export function retainInsight(key: string | null, insight: Partial<InsightModel>): void {
    if (key && insight.query) {
        write(key, insight)
    }
}
