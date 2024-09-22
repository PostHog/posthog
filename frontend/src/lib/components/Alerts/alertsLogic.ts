import { afterMount, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { AlertState, AlertType } from '~/queries/schema'

import { alertsLogicType } from './alertsLogicType'

export interface AlertsLogicProps {}

export const alertsLogic = kea<alertsLogicType>([
    path(['lib', 'components', 'Alerts', 'alertsLogic']),
    props({} as AlertsLogicProps),

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
            (alerts: AlertType[]) => alerts.sort((a, b) => alertComparatorKey(a) - alertComparatorKey(b)),
        ],
    }),

    afterMount(({ actions }) => actions.loadAlerts()),
])

const alertComparatorKey = (alert: AlertType): number =>
    !alert.enabled ? 3 : alert.state === AlertState.NOT_FIRING ? 2 : 1
