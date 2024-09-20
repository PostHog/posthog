import { actions, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { AlertType, AlertTypeWrite } from '~/queries/schema'

import type { alertFormLogicType } from './alertFormLogicType'

export type AlertFormType = Pick<
    AlertType,
    'name' | 'enabled' | 'created_at' | 'threshold' | 'subscribed_users' | 'checks' | 'insight' | 'insight_short_id'
> & {
    id?: AlertType['id']
    created_by: AlertType['created_by'] | null
}

export interface AlertFormLogicProps {
    alert: AlertFormType
    onEditSuccess: () => void
    onCreateSuccess?: () => void
    onDeleteSuccess?: () => void
}

export const alertFormLogic = kea<alertFormLogicType>([
    path(['lib', 'components', 'Alerts', 'alertFormLogic']),
    props({} as AlertFormLogicProps),
    key(({ alert }) => alert.id ?? 'new'),

    actions({
        deleteAlert: true,
    }),

    forms(({ props }) => ({
        alert: {
            defaults: props.alert,
            errors: ({ name }) => ({
                name: !name ? 'You need to give your alert a name' : undefined,
            }),
            submit: async (alert) => {
                const payload: Partial<AlertTypeWrite> = {
                    ...alert,
                    subscribed_users: alert.subscribed_users?.map(({ id }) => id),
                }

                try {
                    if (alert.id === undefined) {
                        const updatedAlert: AlertType = await api.alerts.create(payload)
                        lemonToast.success(`Alert created.`)
                        props.onCreateSuccess?.()
                        return updatedAlert
                    }

                    const updatedAlert: AlertType = await api.alerts.update(alert.id, payload)
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

    listeners(({ props, values }) => ({
        deleteAlert: async () => {
            // deletion only allowed on created alert (which will have alertId)
            if (!values.alert.id) {
                throw new Error("Cannot delete alert that doesn't exist")
            }
            await api.alerts.delete(values.alert.id)
            props.onEditSuccess()
            props.onDeleteSuccess?.()
        },

        submitAlertSuccess: () => {
            props.onEditSuccess()
        },
    })),
])
