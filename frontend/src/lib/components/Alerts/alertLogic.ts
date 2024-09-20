import { actions, events, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
// import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { AlertType, AlertTypeWrite } from '~/queries/schema'

import type { alertLogicType } from './alertLogicType'

export interface AlertLogicProps {
    alertId?: string
    onEditSuccess: () => void
}

export const alertLogic = kea<alertLogicType>([
    path(['lib', 'components', 'Alerts', 'alertLogic']),
    props({} as AlertLogicProps),
    key(({ alertId }) => alertId ?? 'new'),

    loaders(({ props }) => ({
        alert: {
            __default: undefined as unknown as AlertType,
            loadAlert: async () => {
                if (props.alertId) {
                    return await api.alerts.get(props.alertId)
                }
                return {
                    enabled: true,
                }
            },
        },
    })),

    actions({
        deleteAlert: true,
    }),

    forms(({ props, actions }) => ({
        alert: {
            defaults: {} as unknown as AlertType,
            errors: ({ name }) => ({
                name: !name ? 'You need to give your alert a name' : undefined,
            }),
            submit: async (alert) => {
                const payload: AlertTypeWrite = {
                    ...alert,
                    subscribed_users: alert.subscribed_users?.map(({ id }) => id),
                }

                try {
                    const updatedAlert: AlertType = !props.alertId
                        ? await api.alerts.create(payload)
                        : await api.alerts.update(props.alertId, payload)

                    actions.resetAlert()

                    actions.loadAlertSuccess(updatedAlert)
                    lemonToast.success(`Alert saved.`)

                    return updatedAlert
                } catch (error: any) {
                    const field = error.data?.attr?.replace(/_/g, ' ')
                    lemonToast.error(`Error saving alert: ${field}: ${error.detail}`)
                    throw error
                }
            },
        },
    })),

    listeners(({ props }) => ({
        deleteAlert: async () => {
            // deletion only allowed on created alert (which will have alertId)
            await api.alerts.delete(props.alertId!)
            props.onEditSuccess()
        },

        submitAlertSuccess: () => {
            props.onEditSuccess()
        },
    })),

    events(({ actions }) => ({
        afterMount() {
            actions.loadAlert()
        },
    })),
])
