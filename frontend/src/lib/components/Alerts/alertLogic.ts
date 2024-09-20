import { events, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { AlertType } from '~/queries/schema'

import type { alertLogicType } from './alertLogicType'

export interface AlertLogicProps {
    alertId?: string
}

export const alertLogic = kea<alertLogicType>([
    path(['lib', 'components', 'Alerts', 'alertLogic']),
    props({} as AlertLogicProps),
    key(({ alertId }) => alertId ?? 'new'),

    loaders(({ props }) => ({
        alert: [
            null as AlertType | null,
            {
                loadAlert: async () => {
                    if (!props.alertId) {
                        return null
                    }
                    return await api.alerts.get(props.alertId)
                },
            },
        ],
    })),

    events(({ actions }) => ({
        afterMount() {
            actions.loadAlert()
        },
    })),
])
