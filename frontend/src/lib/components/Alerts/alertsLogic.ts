import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { getInsightId } from 'scenes/insights/utils'

import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { AlertType, ChartDisplayType, InsightShortId } from '~/types'

import type { alertsLogicType } from './alertsLogicType'

export interface AlertsLogicProps {
    insightShortId: InsightShortId
}

export const areAlertsSupportedForInsight = (query?: Record<string, any> | null): boolean => {
    return (
        !!query &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        query.source.trendsFilter != null &&
        query.source.trendsFilter.display == ChartDisplayType.BoldNumber
    )
}

export const alertsLogic = kea<alertsLogicType>([
    path(['lib', 'components', 'Alerts', 'alertsLogic']),
    props({} as AlertsLogicProps),
    key(({ insightShortId }) => `insight-${insightShortId}`),
    actions({
        deleteAlert: (id: number) => ({ id }),
    }),

    loaders(({ props }) => ({
        alerts: {
            __default: [] as AlertType[],
            loadAlerts: async () => {
                const insightId = await getInsightId(props.insightShortId)
                if (!insightId) {
                    return []
                }
                const response = await api.alerts.list(insightId)
                return response.results
            },
        },
    })),

    reducers({
        alerts: {
            deleteAlert: (state, { id }) => state.filter((a) => a.id !== id),
        },
    }),

    listeners({
        deleteAlert: async ({ id }) => {
            await api.alerts.delete(id)
        },
    }),

    afterMount(({ actions }) => actions.loadAlerts()),
])
