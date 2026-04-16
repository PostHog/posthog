import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { anomaliesLogicType } from './anomaliesLogicType'
import { AnomalyInterval, AnomalyScoreType, AnomalyWindow } from './types'

export const anomaliesLogic = kea<anomaliesLogicType>([
    path(['lib', 'components', 'Anomalies', 'anomaliesLogic']),

    actions({
        setWindow: (window: AnomalyWindow) => ({ window }),
        setSearch: (search: string) => ({ search }),
        setIntervalFilter: (interval: AnomalyInterval) => ({ interval }),
    }),

    reducers({
        window: [
            '30d' as AnomalyWindow,
            {
                setWindow: (_, { window }) => window,
            },
        ],
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
            },
        ],
        intervalFilter: [
            '' as AnomalyInterval,
            {
                setIntervalFilter: (_, { interval }) => interval,
            },
        ],
    }),

    loaders(({ values }) => ({
        anomalies: {
            __default: [] as AnomalyScoreType[],
            loadAnomalies: async () => {
                const params = new URLSearchParams()
                params.set('window', values.window)
                params.set('anomalous_only', 'true')
                if (values.search) {
                    params.set('search', values.search)
                }
                if (values.intervalFilter) {
                    params.set('interval', values.intervalFilter)
                }
                const response = await api.get(`api/environments/@current/anomalies/?${params.toString()}`)
                return response.results
            },
        },
    })),

    selectors({
        filteredAnomalies: [
            (s) => [s.anomalies],
            (anomalies: AnomalyScoreType[]): AnomalyScoreType[] => {
                return [...anomalies].sort((a, b) => b.score - a.score)
            },
        ],
    }),

    listeners(({ actions }) => ({
        setWindow: () => actions.loadAnomalies(),
        setSearch: () => actions.loadAnomalies(),
        setIntervalFilter: () => actions.loadAnomalies(),
    })),

    afterMount(({ actions }) => actions.loadAnomalies()),
])
