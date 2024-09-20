import { actions, afterMount, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { AlertType } from '~/queries/schema'

import { alertsLogicType } from './alertsLogicType'

export interface AlertsLogicProps {}

export const alertsLogic = kea<alertsLogicType>([
    path(['lib', 'components', 'Alerts', 'alertsLogic']),
    props({} as AlertsLogicProps),
    actions({
        // deleteAlert: (id: string) => ({ id }),
        // setShouldShowAlertDeletionWarning: (show: boolean) => ({ show }),
    }),

    // connect((props: AlertsLogicProps) => ({
    //     actions: [insightVizDataLogic(props.insightLogicProps), ['setQuery']],
    // })),

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
            (alerts: AlertType[]) => alerts.sort((a, b) => (a.state === 'firing' ? -1 : b.state === 'firing' ? 1 : 0)),
        ],
    }),

    reducers({
        alerts: {
            deleteAlert: (state, { id }) => state.filter((a) => a.id !== id),
        },
        // shouldShowAlertDeletionWarning: [
        //     false,
        //     {
        //         setShouldShowAlertDeletionWarning: (_, { show }) => show,
        //     },
        // ],
    }),

    // listeners(({ actions, values, props }) => ({
    //     deleteAlert: async ({ id }) => {
    //         await api.alerts.delete(props.insightId, id)
    //     },
    // })),

    afterMount(({ actions }) => actions.loadAlerts()),
])
