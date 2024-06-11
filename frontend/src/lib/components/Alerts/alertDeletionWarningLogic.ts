import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

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
        values: [alertsLogic({ insightShortId: props.dashboardItemId! as InsightShortId }), ['alerts']],
        actions: [insightVizDataLogic, ['setQuery']],
    })),
    listeners(({ actions, values }) => ({
        setQuery: ({ query }) => {
            if (values.alerts.length === 0 || areAlertsSupportedForInsight(query)) {
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
