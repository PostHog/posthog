import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'

import type { dashboardQueryCacheLogicType } from './dashboardQueryCacheLogicType'

export interface DashboardQueryCacheLogicProps {
    id: number
}

export interface CachedResult {
    result: any
    filtersHash: string
    timestamp: number
}

const MAX_CACHE_ENTRIES = 500
let cacheInsertionOrder = 0

function stableStringify(obj: any): string {
    if (obj === null || obj === undefined || typeof obj !== 'object') {
        return JSON.stringify(obj)
    }
    if (Array.isArray(obj)) {
        return '[' + obj.map(stableStringify).join(',') + ']'
    }
    const keys = Object.keys(obj).sort()
    return '{' + keys.map((k) => JSON.stringify(k) + ':' + stableStringify(obj[k])).join(',') + '}'
}

function hashFilters(filters: DashboardFilter, variables: Record<string, HogQLVariable>): string {
    return `${stableStringify(filters)}:${stableStringify(variables)}`
}

export const dashboardQueryCacheLogic = kea<dashboardQueryCacheLogicType>([
    path(['scenes', 'dashboard', 'dashboardQueryCacheLogic']),
    props({} as DashboardQueryCacheLogicProps),

    key((props) => {
        if (typeof props.id !== 'number') {
            throw Error('Must init dashboardQueryCacheLogic with a numeric ID key')
        }
        return props.id
    }),

    actions({
        setCachedResult: (insightId: number, filtersHash: string, result: any) => ({
            insightId,
            filtersHash,
            result,
        }),
        invalidateCache: (insightIds?: number[]) => ({ insightIds }),
    }),

    reducers({
        cache: [
            {} as Record<string, CachedResult>,
            {
                setCachedResult: (state, { insightId, filtersHash, result }) => {
                    const cacheKey = `${insightId}:${filtersHash}`
                    const newCache = {
                        ...state,
                        [cacheKey]: {
                            result,
                            filtersHash,
                            timestamp: ++cacheInsertionOrder,
                        },
                    }
                    const keys = Object.keys(newCache)
                    if (keys.length > MAX_CACHE_ENTRIES) {
                        const oldest = keys.reduce((a, b) => (newCache[a].timestamp < newCache[b].timestamp ? a : b))
                        delete newCache[oldest]
                    }
                    return newCache
                },
                invalidateCache: (state, { insightIds }) => {
                    if (!insightIds) {
                        return {}
                    }
                    const newCache = { ...state }
                    for (const key of Object.keys(newCache)) {
                        const id = parseInt(key.split(':')[0], 10)
                        if (insightIds.includes(id)) {
                            delete newCache[key]
                        }
                    }
                    return newCache
                },
            },
        ],
    }),

    selectors({
        getCachedResult: [
            (s) => [s.cache],
            (cache) =>
                (insightId: number, filters: DashboardFilter, variables: Record<string, HogQLVariable>): any | null => {
                    const key = `${insightId}:${hashFilters(filters, variables)}`
                    return cache[key]?.result ?? null
                },
        ],
    }),
])

export { hashFilters }
