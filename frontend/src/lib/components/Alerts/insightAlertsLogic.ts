import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { getBreakdown, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { InsightLogicProps, InsightShortId } from '~/types'

import type { insightAlertsLogicType } from './insightAlertsLogicType'
import { AlertType } from './types'

export interface InsightAlertsLogicProps {
    insightId: number
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

export const areAlertsSupportedForInsight = (query?: Record<string, any> | null): boolean => {
    return (
        !!query &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        query.source.trendsFilter !== null &&
        !getBreakdown(query.source)
    )
}

export const insightAlertsLogic = kea<insightAlertsLogicType>([
    path(['lib', 'components', 'Alerts', 'insightAlertsLogic']),
    props({} as InsightAlertsLogicProps),
    key(({ insightId }) => `insight-${insightId}`),
    actions({
        setShouldShowAlertDeletionWarning: (show: boolean) => ({ show }),
    }),

    connect((props: InsightAlertsLogicProps) => ({
        actions: [insightVizDataLogic(props.insightLogicProps), ['setQuery']],
    })),

    loaders(({ props }) => ({
        alerts: {
            __default: [] as AlertType[],
            loadAlerts: async () => {
                const response = await api.alerts.list(props.insightId)

                return response.results
            },
        },
    })),

    reducers({
        alerts: {
            deleteAlert: (state, { alertId }) => state.filter((a) => a.id !== alertId),
        },
        shouldShowAlertDeletionWarning: [
            false,
            {
                setShouldShowAlertDeletionWarning: (_, { show }) => show,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        deleteAlert: async ({ alertId }) => {
            await api.alerts.delete(alertId)
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
