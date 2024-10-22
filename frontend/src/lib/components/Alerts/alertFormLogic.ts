import { actions, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { AlertCalculationInterval, AlertConditionType, InsightThresholdType } from '~/queries/schema'
import { QueryBasedInsightModel } from '~/types'

import type { alertFormLogicType } from './alertFormLogicType'
import { AlertType, AlertTypeWrite } from './types'

export type AlertFormType = Pick<
    AlertType,
    'name' | 'enabled' | 'created_at' | 'threshold' | 'condition' | 'subscribed_users' | 'checks' | 'config'
> & {
    id?: AlertType['id']
    created_by?: AlertType['created_by'] | null
    insight?: QueryBasedInsightModel['id']
}

export interface AlertFormLogicProps {
    alert: AlertType | null
    insightId: QueryBasedInsightModel['id']
    onEditSuccess: () => void
}

export const alertFormLogic = kea<alertFormLogicType>([
    path(['lib', 'components', 'Alerts', 'alertFormLogic']),
    props({} as AlertFormLogicProps),
    key(({ alert }) => alert?.id ?? 'new'),

    actions({
        deleteAlert: true,
        snoozeAlert: (snoozeUntil: string) => ({ snoozeUntil }),
        clearSnooze: true,
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
                    threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: {} } },
                    condition: {
                        type: AlertConditionType.ABSOLUTE_VALUE,
                    },
                    subscribed_users: [],
                    checks: [],
                    calculation_interval: AlertCalculationInterval.DAILY,
                    insight: props.insightId,
                } as AlertFormType),
            errors: ({ name }) => ({
                name: !name ? 'You need to give your alert a name' : undefined,
            }),
            submit: async (alert) => {
                const payload: AlertTypeWrite = {
                    ...alert,
                    subscribed_users: alert.subscribed_users?.map(({ id }) => id),
                    insight: props.insightId,
                }

                // absolute value alert can only have absolute threshold
                if (payload.condition.type === AlertConditionType.ABSOLUTE_VALUE) {
                    payload.threshold.configuration.type = InsightThresholdType.ABSOLUTE
                }

                try {
                    if (alert.id === undefined) {
                        const updatedAlert: AlertType = await api.alerts.create(payload)

                        lemonToast.success(`Alert created.`)
                        props.onEditSuccess()

                        return updatedAlert
                    }

                    const updatedAlert: AlertType = await api.alerts.update(alert.id, payload)

                    lemonToast.success(`Alert saved.`)
                    props.onEditSuccess()

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
        },
        snoozeAlert: async ({ snoozeUntil }) => {
            // resolution only allowed on created alert (which will have alertId)
            if (!values.alertForm.id) {
                throw new Error("Cannot resolve alert that doesn't exist")
            }
            await api.alerts.update(values.alertForm.id, { snoozed_until: snoozeUntil })
            props.onEditSuccess()
        },
        clearSnooze: async () => {
            // resolution only allowed on created alert (which will have alertId)
            if (!values.alertForm.id) {
                throw new Error("Cannot resolve alert that doesn't exist")
            }
            await api.alerts.update(values.alertForm.id, { snoozed_until: null })
            props.onEditSuccess()
        },
    })),
])
