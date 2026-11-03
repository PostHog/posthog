import { getContext } from 'kea'

import { RetainedValues, setBackgroundTimeout } from 'lib/utils/retainedValues'

import { AnyResponseType } from '~/queries/schema/schema-general'

import type { DataNodeLogicProps } from './dataNodeLogic'

export const RESPONSE_CACHE_TTL = 10 * 60 * 1000
export const MAX_RETAINED_RESPONSE_LENGTH = 10_000_000
/** How long a query keeps running after its node unmounts, waiting for a remount to pick it up. */
export const ABANDONED_QUERY_GRACE_PERIOD = 60 * 1000

// Sizes are in serialized characters. The keys already name the user and project.
const retainedResponses = new RetainedValues<AnyResponseType>({
    maxEntries: 500,
    ttlMs: RESPONSE_CACHE_TTL,
    maxTotalSize: 50_000_000,
    maxEntrySize: MAX_RETAINED_RESPONSE_LENGTH,
    scopeToProject: false,
})

export type InflightQuery = {
    promise: Promise<AnyResponseType | null>
    /** The id the request was submitted with, which a node that adopts it shows and cancels by. */
    queryId: string
    /** Stops the query for a node that loads again. Forgets it at once, so the next load can't rejoin it. */
    abort: () => void
    /** Starts the grace period. A query nobody adopts in time is abandoned. */
    release: () => void
    adopt: () => void
}
type InflightQueries = {
    byKey: Map<string, InflightQuery>
    /** Queries waiting out their grace period, oldest first, with the function that abandons each one. */
    released: Map<InflightQuery, () => void>
}
const inflightQueries = new WeakMap<ReturnType<typeof getContext>, InflightQueries>()

function getInflightQueries(): InflightQueries {
    const context = getContext()
    let queries = inflightQueries.get(context)
    if (!queries) {
        queries = { byKey: new Map(), released: new Map() }
        inflightQueries.set(context, queries)
    }
    return queries
}

/** Abandons the oldest query that no node uses, so a query someone is waiting for can take its slot. */
export function reclaimReleasedQuery(): boolean {
    const { released } = getInflightQueries()
    const oldest = released.entries().next().value
    if (!oldest) {
        return false
    }
    oldest[1]()
    return true
}

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

export function getRetainedResponse(key: string | null): AnyResponseType | null {
    const response = key ? retainedResponses.get(key) : null
    return response ? structuredClone(response) : null
}

export function forgetRetainedResponse(key: string | null): void {
    if (key) {
        retainedResponses.delete(key)
    }
}

export function retainResponse(key: string | null, response: AnyResponseType | null | undefined): void {
    retainWith(retainedResponses.set.bind(retainedResponses), key, response)
}

function retainWith(
    set: (key: string, response: AnyResponseType, size: number) => void,
    key: string | null,
    response: AnyResponseType | null | undefined
): void {
    if (!key || !isCompleteResponse(response)) {
        return
    }
    const serialized = JSON.stringify(response)
    if (serialized.length <= MAX_RETAINED_RESPONSE_LENGTH) {
        set(key, JSON.parse(serialized), serialized.length)
    }
}

export function getInflightResponse(key: string | null): InflightQuery | null {
    return key ? (getInflightQueries().byKey.get(key) ?? null) : null
}

/**
 * Lets a query outlive the data node that started it. A node that remounts with the same key awaits
 * the running request instead of cancelling it and starting over, and the result is retained.
 */
export function trackInflightResponse(
    key: string,
    promise: Promise<AnyResponseType | null>,
    { queryId, abort, abandon }: { queryId: string; abort: () => void; abandon: () => void }
): InflightQuery {
    const { byKey, released } = getInflightQueries()
    const retain = retainedResponses.bindSet()
    let settled = false
    let graceTimer: ReturnType<typeof setTimeout> | null = null
    const stopGraceTimer = (): void => {
        if (graceTimer) {
            clearTimeout(graceTimer)
            graceTimer = null
        }
        released.delete(query)
    }
    const forget = (): void => {
        stopGraceTimer()
        if (byKey.get(key) === query) {
            byKey.delete(key)
        }
    }
    const abandonNow = (): void => {
        forget()
        abandon()
    }
    const query: InflightQuery = {
        promise,
        queryId,
        abort: () => {
            forget()
            abort()
        },
        release: () => {
            if (settled) {
                return
            }
            stopGraceTimer()
            released.set(query, abandonNow)
            graceTimer = setBackgroundTimeout(abandonNow, ABANDONED_QUERY_GRACE_PERIOD)
        },
        adopt: stopGraceTimer,
    }
    byKey.set(key, query)
    promise
        .then((response) => retainWith(retain, key, response))
        .catch(() => {})
        .finally(() => {
            settled = true
            forget()
        })
    return query
}
