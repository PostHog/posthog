import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import {
    AlertCalculationInterval,
    AlertConditionType,
    ForecastAlertConfig,
    GoalLine,
    InsightThresholdType,
    InsightsThresholdBounds,
    TrendsAlertConfig,
} from '~/queries/schema/schema-general'
import { InsightLogicProps, QueryBasedInsightModel } from '~/types'

import type { alertFormLogicType } from './alertFormLogicType'
import { insightAlertsLogic } from './insightAlertsLogic'
import { AlertType, AlertTypeWrite } from './types'

export type AlertFormType = Pick<
    AlertType,
    | 'name'
    | 'enabled'
    | 'created_at'
    | 'calculation_interval'
    | 'threshold'
    | 'condition'
    | 'subscribed_users'
    | 'checks'
    | 'config'
    | 'skip_weekend'
> & {
    id?: AlertType['id']
    created_by?: AlertType['created_by'] | null
    insight?: QueryBasedInsightModel['id']
}

export function canCheckOngoingInterval(alert?: AlertType | AlertFormType): boolean {
    // Forecast alerts don't support ongoing interval checking
    if (alert?.condition.type === AlertConditionType.FORECAST_DEVIATION) {
        return false
    }
    return (
        (alert?.condition.type === AlertConditionType.ABSOLUTE_VALUE ||
            alert?.condition.type === AlertConditionType.RELATIVE_INCREASE) &&
        alert?.threshold.configuration.bounds?.upper != null &&
        !isNaN(alert?.threshold.configuration.bounds.upper)
    )
}

export interface AlertFormLogicProps {
    alert: AlertType | null
    insightId: QueryBasedInsightModel['id']
    onEditSuccess: (alertId?: AlertType['id']) => void
    insightVizDataLogicProps?: InsightLogicProps
}

const getThresholdBounds = (goalLines?: GoalLine[] | null): InsightsThresholdBounds => {
    if (goalLines == null || goalLines.length == 0) {
        return {}
    }

    // Simple assumption that the alert should be triggered when the first/smallest goal line is crossed
    const smallerValue = Math.min(...goalLines.map((line) => line.value))
    return { upper: smallerValue }
}

export const alertFormLogic = kea<alertFormLogicType>([
    path(['lib', 'components', 'Alerts', 'alertFormLogic']),
    props({} as AlertFormLogicProps),
    key(({ alert }) => alert?.id ?? 'new'),

    connect((props: AlertFormLogicProps) => ({
        values: [trendsDataLogic({ dashboardId: undefined, ...props.insightVizDataLogicProps }), ['goalLines']],
    })),

    actions({
        deleteAlert: true,
        snoozeAlert: (snoozeUntil: string) => ({ snoozeUntil }),
        clearSnooze: true,
        setGenerateHistoricalForecasts: (value: boolean) => ({ value }),
    }),

    reducers({
        generateHistoricalForecasts: [
            true, // Default to true for new forecast alerts
            {
                setGenerateHistoricalForecasts: (_, { value }) => value,
            },
        ],
    }),

    forms(({ props, values }) => ({
        alertForm: {
            defaults:
                props.alert ??
                ({
                    id: undefined,
                    name: values.goalLines && values.goalLines.length > 0 ? `Crossed ${values.goalLines[0].label}` : '',
                    created_by: null,
                    created_at: '',
                    enabled: true,
                    config: {
                        type: 'TrendsAlertConfig',
                        series_index: 0,
                        check_ongoing_interval: false,
                        confidence_level: 0.95,
                    } as TrendsAlertConfig & { confidence_level?: number },
                    threshold: {
                        configuration: {
                            type: InsightThresholdType.ABSOLUTE,
                            bounds: getThresholdBounds(values.goalLines),
                        },
                    },
                    condition: {
                        type: AlertConditionType.ABSOLUTE_VALUE,
                    },
                    subscribed_users: [],
                    checks: [],
                    calculation_interval: AlertCalculationInterval.DAILY,
                    skip_weekend: false,
                    insight: props.insightId,
                } as AlertFormType),
            errors: ({ name }) => ({
                name: !name ? 'You need to give your alert a name' : undefined,
            }),
            submit: async (alert) => {
                const isForecastAlert = alert.condition.type === AlertConditionType.FORECAST_DEVIATION

                // Build the appropriate config based on alert type
                const config = isForecastAlert
                    ? ({
                          type: 'ForecastAlertConfig',
                          series_index: alert.config.series_index,
                          confidence_level: (alert.config as ForecastAlertConfig).confidence_level ?? 0.95,
                      } as ForecastAlertConfig)
                    : ({
                          type: 'TrendsAlertConfig',
                          series_index: alert.config.series_index,
                          check_ongoing_interval:
                              canCheckOngoingInterval(alert) &&
                              (alert.config as TrendsAlertConfig).check_ongoing_interval,
                      } as TrendsAlertConfig)

                const payload: AlertTypeWrite = {
                    ...alert,
                    subscribed_users: alert.subscribed_users?.map(({ id }) => id),
                    insight: props.insightId,
                    // can only skip weekends for hourly/daily alerts
                    skip_weekend:
                        (alert.calculation_interval === AlertCalculationInterval.DAILY ||
                            alert.calculation_interval === AlertCalculationInterval.HOURLY) &&
                        alert.skip_weekend,
                    config,
                }

                // absolute value alert can only have absolute threshold
                if (payload.condition.type === AlertConditionType.ABSOLUTE_VALUE) {
                    payload.threshold.configuration.type = InsightThresholdType.ABSOLUTE
                }

                try {
                    let updatedAlert: AlertType
                    if (alert.id === undefined) {
                        updatedAlert = await api.alerts.create(payload)
                        lemonToast.success(`Alert created.`)
                    } else {
                        updatedAlert = await api.alerts.update(alert.id, payload)
                        lemonToast.success(`Alert saved.`)
                    }

                    props.onEditSuccess(updatedAlert.id)

                    // Trigger backfill if this is a forecast alert and the checkbox is checked
                    if (isForecastAlert && values.generateHistoricalForecasts && updatedAlert.id) {
                        try {
                            await api.alerts.backfill(updatedAlert.id)
                            lemonToast.info('Generating historical forecasts in the background...')
                        } catch (backfillError) {
                            console.error('Failed to trigger backfill:', backfillError)
                        }
                    }

                    return updatedAlert
                } catch (error: any) {
                    const field = error.data?.attr?.replace(/_/g, ' ')
                    lemonToast.error(`Error saving alert: ${field}: ${error.detail}`)
                    throw error
                }
            },
        },
    })),

    listeners(({ props, values }) => {
        // Helper to refresh alerts in the parent logic if available
        const refreshParentAlerts = (): void => {
            if (props.insightVizDataLogicProps) {
                insightAlertsLogic({
                    insightId: props.insightId,
                    insightLogicProps: props.insightVizDataLogicProps,
                }).actions.loadAlerts()
            }
        }

        return {
            deleteAlert: async () => {
                // deletion only allowed on created alert (which will have alertId)
                if (!values.alertForm.id) {
                    throw new Error("Cannot delete alert that doesn't exist")
                }
                await api.alerts.delete(values.alertForm.id)
                lemonToast.success('Alert deleted.')
                refreshParentAlerts()
                props.onEditSuccess(undefined)
            },
            snoozeAlert: async ({ snoozeUntil }) => {
                // snoozing only allowed on created alert (which will have alertId)
                if (!values.alertForm.id) {
                    throw new Error("Cannot snooze alert that doesn't exist")
                }
                await api.alerts.update(values.alertForm.id, { snoozed_until: snoozeUntil })
                refreshParentAlerts()
                props.onEditSuccess(values.alertForm.id)
            },
            clearSnooze: async () => {
                // resolution only allowed on created alert (which will have alertId)
                if (!values.alertForm.id) {
                    throw new Error("Cannot resolve alert that doesn't exist")
                }
                await api.alerts.update(values.alertForm.id, { snoozed_until: null })
                refreshParentAlerts()
                props.onEditSuccess(values.alertForm.id)
            },
            submitAlertFormSuccess: () => {
                refreshParentAlerts()
            },
        }
    }),
])
