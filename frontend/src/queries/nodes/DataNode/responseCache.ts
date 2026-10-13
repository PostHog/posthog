import { getContext } from 'kea'

import { AnyResponseType } from '~/queries/schema/schema-general'

import type { DataNodeLogicProps } from './dataNodeLogic'

const MAX_ENTRIES = 100
const MAX_ENTRY_LENGTH = 200_000
export const RESPONSE_CACHE_TTL = 2 * 60 * 1000

type Entry = { response: AnyResponseType; expiresAt: number }
const caches = new WeakMap<ReturnType<typeof getContext>, Map<string, Entry>>()

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

function getCache(): Map<string, Entry> {
    const context = getContext()
    let cache = caches.get(context)
    if (!cache) {
        cache = new Map()
        caches.set(context, cache)
    }
    return cache
}

export function getRetainedResponse(key: string | null): AnyResponseType | null {
    if (!key) {
        return null
    }
    const cache = getCache()
    const entry = cache.get(key)
    if (!entry || entry.expiresAt <= Date.now()) {
        cache.delete(key)
        return null
    }
    cache.delete(key)
    cache.set(key, entry)
    return structuredClone(entry.response)
}

export function forgetRetainedResponse(key: string | null): void {
    if (key) {
        getCache().delete(key)
    }
}

export function retainResponse(key: string | null, response: AnyResponseType | null | undefined): void {
    if (!key || !isCompleteResponse(response)) {
        return
    }
    const serialized = JSON.stringify(response)
    if (serialized.length > MAX_ENTRY_LENGTH) {
        return
    }
    const cache = getCache()
    cache.delete(key)
    cache.set(key, { response: JSON.parse(serialized), expiresAt: Date.now() + RESPONSE_CACHE_TTL })
    while (cache.size > MAX_ENTRIES) {
        cache.delete(cache.keys().next().value!)
    }
}
