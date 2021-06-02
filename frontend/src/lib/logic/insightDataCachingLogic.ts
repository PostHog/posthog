import { kea } from 'kea'
import api from 'lib/api'
import { insightDataCachingLogicType } from './insightDataCachingLogicType'

const STALENESS_THRESHOLD_MS = 180000

export const insightDataCachingLogic = kea<insightDataCachingLogicType>({
    actions: {
        maybeLoadData: (payload: { key: string; endpoint: string; paginated?: boolean }) => payload,
        setLoading: (key: string, loading: boolean) => ({ key, loading }),
    },
    loaders: ({ values, actions }) => ({
        cachedData: {
            __default: {} as Record<string, any>,
            refreshData: async (payload: { key: string; endpoint: string }) => {
                actions.setLoading(payload.key, true)
                const response = await api.get(payload.endpoint)

                actions.setLoading(payload.key, false)

                return {
                    ...values.cachedData,
                    [payload.key]: response,
                }
            },
            refreshPaginatedData: async (payload: { key: string; endpoint: string; initial?: boolean }) => {
                console.log('refreshPaginatedData called', payload)
                if (payload.initial) {
                    actions.setLoading(payload.key, true)
                }

                const results = payload.initial ? [] : values.cachedData[payload.key].results
                let response: any

                try {
                    response = await api.get(payload.endpoint)
                } catch (err) {
                    actions.setLoading(payload.key, false)
                    throw err
                }

                if (response.next) {
                    // :TRICKY: Fetch next page once this loader has resolved.
                    setTimeout(() => {
                        if (actions) {
                            actions.refreshPaginatedData({ key: payload.key, endpoint: response.next })
                        }
                    }, 0)
                } else {
                    actions.setLoading(payload.key, false)
                }

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
                setLoading: (state, { key, loading }) => (loading ? state : { ...state, [key]: new Date().getTime() }),
            },
        ],
        cacheLoading: [
            {} as Record<string, boolean | undefined>,
            {
                setLoading: (state, { key, loading }) => ({ ...state, [key]: loading }),
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
    return !cacheLoading[key] && time - lastFetch >= STALENESS_THRESHOLD_MS
}
