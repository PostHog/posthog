import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getInsightId } from 'scenes/insights/utils'

import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { AlertType, ChartDisplayType, InsightLogicProps, InsightShortId } from '~/types'

import type { alertsLogicType } from './alertsLogicType'

export interface AlertsLogicProps {
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

export const areAlertsSupportedForInsight = (query?: Record<string, any> | null): boolean => {
    return (
        !!query &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        query.source.trendsFilter !== null &&
        query.source.trendsFilter?.display === ChartDisplayType.BoldNumber
    )
}

export const alertsLogic = kea<alertsLogicType>([
    path(['lib', 'components', 'Alerts', 'alertsLogic']),
    props({} as AlertsLogicProps),
    key(({ insightShortId }) => `insight-${insightShortId}`),
    actions({
        deleteAlert: (id: number) => ({ id }),
        setShouldShowAlertDeletionWarning: (show: boolean) => ({ show }),
    }),

    connect((props: AlertsLogicProps) => ({
        actions: [insightVizDataLogic(props.insightLogicProps), ['setQuery']],
    })),

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
        shouldShowAlertDeletionWarning: [
            false,
            {
                setShouldShowAlertDeletionWarning: (_, { show }) => show,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        deleteAlert: async ({ id }) => {
            await api.alerts.delete(id)
        },
        setQuery: ({ query }) => {
            if (values.alerts.length === 0 || areAlertsSupportedForInsight(query)) {
                actions.setShouldShowAlertDeletionWarning(false)
            } else {
                actions.setShouldShowAlertDeletionWarning(true)
            }
        },
    })),

    afterMount(({ actions }) => actions.loadAlerts()),
])
