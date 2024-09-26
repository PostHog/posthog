import { actions, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { QueryBasedInsightModel } from '~/types'

import type { alertFormLogicType } from './alertFormLogicType'
import { AlertType, AlertTypeWrite } from './types'

export type AlertFormType = Pick<
    AlertType,
    'name' | 'enabled' | 'created_at' | 'threshold' | 'subscribed_users' | 'checks' | 'config'
> & {
    id?: AlertType['id']
    created_by?: AlertType['created_by'] | null
    insight_id?: QueryBasedInsightModel['id']
}

export interface AlertFormLogicProps {
    alert: AlertType | null
    insightId: QueryBasedInsightModel['id']
    onEditSuccess: () => void
    onCreateSuccess?: () => void
    onDeleteSuccess?: () => void
}

export const alertFormLogic = kea<alertFormLogicType>([
    path(['lib', 'components', 'Alerts', 'alertFormLogic']),
    props({} as AlertFormLogicProps),
    key(({ alert }) => alert?.id ?? 'new'),

    actions({
        deleteAlert: true,
    }),

    forms(({ props }) => ({
        alertForm: {
            defaults:
                props.alert ??
                ({
                    id: undefined,
                    name: '',
                    created_by: null,
                    created_at: '',
                    enabled: true,
                    config: {
                        type: 'TrendsAlertConfig',
                        series_index: 0,
                    },
                    threshold: {
                        configuration: {
                            absoluteThreshold: {},
                        },
                    },
                    subscribed_users: [],
                    checks: [],
                    insight: props.insightId,
                } as AlertFormType),
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
            if (!values.alertForm.id) {
                throw new Error("Cannot delete alert that doesn't exist")
            }
            await api.alerts.delete(values.alertForm.id)
            props.onEditSuccess()
            props.onDeleteSuccess?.()
        },

        submitAlertFormSuccess: () => {
            props.onEditSuccess()
        },
    })),
])
