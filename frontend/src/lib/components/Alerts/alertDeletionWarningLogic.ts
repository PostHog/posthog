import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightLogicProps } from '~/types'

import type { alertDeletionWarningLogicType } from './alertDeletionWarningLogicType'
import { alertsLogic, areAlertsSupportedForInsight } from './alertsLogic'

export const alertDeletionWarningLogic = kea<alertDeletionWarningLogicType>([
    path(['lib', 'components', 'Alerts', 'alertDeletionWarningLogic']),
    props({} as InsightLogicProps),
    actions({
        setShouldShow: (show: boolean) => ({ show }),
    }),
    connect((props: InsightLogicProps) => ({
        values: [alertsLogic({ insightShortId: props.dashboardItemId! }), ['alerts']],
        actions: [insightLogic, ['setFilters']],
    })),
    listeners(({ actions, values }) => ({
        setFilters: ({ filters }) => {
            if (values.alerts.length === 0 || areAlertsSupportedForInsight(filters)) {
                actions.setShouldShow(false)
            } else {
                actions.setShouldShow(true)
            }
        },
    })),
    reducers({
        shouldShow: [
            false,
            {
                setShouldShow: (_, { show }) => show,
            },
        ],
    }),
])
