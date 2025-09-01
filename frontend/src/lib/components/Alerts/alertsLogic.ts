import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { AlertState } from '~/queries/schema/schema-general'

import { AlertLogicProps } from './alertLogic'
import type { alertsLogicType } from './alertsLogicType'
import { AlertType } from './types'

export interface AlertsLogicProps extends AlertLogicProps {}

export const alertsLogic = kea<alertsLogicType>([
    path(['lib', 'components', 'Alerts', 'alertsLogic']),

    loaders({
        alerts: {
            __default: [] as AlertType[],
            loadAlerts: async () => {
                const response = await api.alerts.list()
                return response.results
            },
        },
    }),

    selectors({
        alertsSortedByState: [
            (s) => [s.alerts],
            (alerts: AlertType[]): AlertType[] => alerts.sort((a, b) => alertComparatorKey(a) - alertComparatorKey(b)),
        ],
    }),

    afterMount(({ actions }) => actions.loadAlerts()),
])

const alertComparatorKey = (alert: AlertType): number => {
    if (!alert.enabled) {
        return 100
    }

    switch (alert.state) {
        case AlertState.FIRING:
            return 1
        case AlertState.ERRORED:
            return 2
        case AlertState.SNOOZED:
            return 3
        case AlertState.NOT_FIRING:
            return 4
    }
}
