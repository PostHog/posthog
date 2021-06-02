import { kea } from 'kea'
import api from 'lib/api'
import { insightDataCachingLogicType } from './insightDataCachingLogicType'

const CACHE_DURATION_MS = 300000

export const insightDataCachingLogic = kea<insightDataCachingLogicType>({
    actions: {
        maybeLoadData: (payload: { key: string; endpoint: string; paginated?: boolean }) => payload,
        startLoading: (key: string) => ({ key }),
        finishLoading: (key: string) => ({ key }),
    },
    loaders: ({ values, actions }) => ({
        cachedData: {
            __default: {} as Record<string, any>,
            refreshData: async (payload: { key: string; endpoint: string }) => {
                actions.startLoading(payload.key)
                const response = await api.get(payload.endpoint)

                setTimeout(() => {
                    if (actions) {
                        actions.finishLoading(payload.key)
                    }
                }, 0)

                return {
                    ...values.cachedData,
                    [payload.key]: response,
                }
            },
            refreshPaginatedData: async (payload: { key: string; endpoint: string; initial?: boolean }) => {
                if (payload.initial) {
                    actions.startLoading(payload.key)
                }

                const results = payload.initial ? [] : values.cachedData[payload.key].results
                let response: any

                try {
                    response = await api.get(payload.endpoint)
                } catch (err) {
                    actions.finishLoading(payload.key)
                    throw err
                }

                setTimeout(() => {
                    if (actions) {
                        if (response.next) {
                            // :TRICKY: Fetch next page once this loader has resolved.
                            actions.refreshPaginatedData({ key: payload.key, endpoint: response.next })
                        } else {
                            actions.finishLoading(payload.key)
                        }
                    }
                }, 0)

                return {
                    ...values.cachedData,
                    [payload.key]: {
                        count: response.count,
                        results: [...results, ...response.results],
                        next: response.next,
                    },
                }
            },
        },
    }),
    reducers: {
        cacheTime: [
            {} as Record<string, number | undefined>,
            {
                finishLoading: (state, { key }) => ({ ...state, [key]: new Date().getTime() }),
            },
        ],
        cacheLoading: [
            {} as Record<string, boolean | undefined>,
            {
                startLoading: (state, { key }) => ({ ...state, [key]: true }),
                finishLoading: (state, { key }) => ({ ...state, [key]: false }),
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        maybeLoadData: ({ key, endpoint, paginated }) => {
            if (shouldLoadData(key, values.cacheTime, values.cacheLoading)) {
                if (paginated) {
                    actions.refreshPaginatedData({ key, endpoint, initial: true })
                } else {
                    actions.refreshData({ key, endpoint })
                }
            }
        },
    }),
})

function shouldLoadData(
    key: string,
    cacheTime: Record<string, number | undefined>,
    cacheLoading: Record<string, boolean | undefined>
): boolean {
    const time = new Date().getTime()
    const lastFetch = cacheTime[key] || 0
    return !cacheLoading[key] && time - lastFetch >= CACHE_DURATION_MS
}
