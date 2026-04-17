import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'

import type { anomaliesLogicType } from './anomaliesLogicType'
import { AnomalyInterval, AnomalyScoreType, AnomalyWindow } from './types'

export type AnomalyFeedback = 'up' | 'down'

export const anomaliesLogic = kea<anomaliesLogicType>([
    path(['lib', 'components', 'Anomalies', 'anomaliesLogic']),

    actions({
        setWindow: (window: AnomalyWindow) => ({ window }),
        setSearch: (search: string) => ({ search }),
        setIntervalFilter: (interval: AnomalyInterval) => ({ interval }),
        setAnomalyFeedback: (anomaly: AnomalyScoreType, feedback: AnomalyFeedback) => ({ anomaly, feedback }),
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
        feedbackByAnomaly: [
            {} as Record<string, AnomalyFeedback>,
            {
                setAnomalyFeedback: (state, { anomaly, feedback }) => ({ ...state, [anomaly.id]: feedback }),
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
        setAnomalyFeedback: ({ anomaly, feedback }) => {
            posthog.capture('anomaly feedback', {
                rating: feedback === 'up' ? 'thumbs_up' : 'thumbs_down',
                anomaly_id: anomaly.id,
                insight_id: anomaly.insight_id,
                insight_short_id: anomaly.insight_short_id,
                series_index: anomaly.series_index,
                series_label: anomaly.series_label,
                score: anomaly.score,
                interval: anomaly.interval,
                // Feedback targets the most recent anomaly on the series; the
                // count tells us whether the user is judging a one-off or a
                // pattern.
                anomaly_timestamp: anomaly.timestamp,
                anomaly_count: anomaly.anomaly_count,
                scored_at: anomaly.scored_at,
            })
        },
    })),

    afterMount(({ actions }) => actions.loadAnomalies()),
])
