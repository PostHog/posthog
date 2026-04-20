import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms, type DeepPartialMap, type ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import {
    AlertCalculationInterval,
    AlertConditionType,
    GoalLine,
    InsightThresholdType,
    InsightsThresholdBounds,
} from '~/queries/schema/schema-general'
import { InsightLogicProps, IntervalType, QueryBasedInsightModel } from '~/types'

import type { alertFormLogicType } from './alertFormLogicType'
import { alertLogic } from './alertLogic'
import { alertNotificationLogic } from './alertNotificationLogic'
import { insightAlertsLogic } from './insightAlertsLogic'
import { quietHoursFormError } from './scheduleRestrictionValidation'
import { AlertSimulationResult, AlertType, AlertTypeWrite, AnomalyPoint } from './types'

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
    | 'schedule_restriction'
    | 'detector_config'
> & {
    id?: AlertType['id']
    created_by?: AlertType['created_by'] | null
    insight?: QueryBasedInsightModel['id']
}

export function canCheckOngoingInterval(alert?: AlertType | AlertFormType): boolean {
    return (
        (alert?.condition.type === AlertConditionType.ABSOLUTE_VALUE ||
            alert?.condition.type === AlertConditionType.RELATIVE_INCREASE) &&
        alert?.threshold.configuration.bounds?.upper != null &&
        !isNaN(alert?.threshold.configuration.bounds.upper)
    )
}

export function getDefaultSimulationRange(interval: AlertCalculationInterval): string {
    switch (interval) {
        case AlertCalculationInterval.HOURLY:
            return '-48h'
        case AlertCalculationInterval.DAILY:
            return '-30d'
        case AlertCalculationInterval.WEEKLY:
            return '-12w'
        case AlertCalculationInterval.MONTHLY:
            return '-12m'
    }
}

export interface AlertFormLogicProps {
    alert: AlertType | null
    insightId: QueryBasedInsightModel['id']
    onEditSuccess: (alertId?: AlertType['id']) => void
    insightVizDataLogicProps?: InsightLogicProps
    insightInterval?: IntervalType
}

/** Apply create/update/snooze API response to alertLogic so UI (e.g. next planned evaluation) updates immediately. */
function hydrateAlertLogicFromSaveResponse(updatedAlert: AlertType): void {
    alertLogic({ alertId: updatedAlert.id }).actions.loadAlertSuccess(updatedAlert)
}

function insightIntervalToAlertInterval(interval?: IntervalType | null): AlertCalculationInterval {
    switch (interval) {
        case 'hour':
            return AlertCalculationInterval.HOURLY
        case 'week':
            return AlertCalculationInterval.WEEKLY
        case 'month':
            return AlertCalculationInterval.MONTHLY
        default:
            return AlertCalculationInterval.DAILY
    }
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
        simulateAlert: true,
        clearSimulation: true,
        setSimulationDateFrom: (dateFrom: string) => ({ dateFrom }),
    }),

    reducers({
        simulationDateFrom: [
            null as string | null,
            {
                setSimulationDateFrom: (_, { dateFrom }) => dateFrom,
            },
        ],
    }),

    loaders(({ props, values }) => ({
        simulationResult: [
            null as AlertSimulationResult | null,
            {
                simulateAlert: async (): Promise<AlertSimulationResult | null> => {
                    const detectorConfig = values.alertForm.detector_config
                    if (!detectorConfig || !props.insightId) {
                        return null
                    }
                    return await api.alerts.simulate({
                        insight: props.insightId,
                        detector_config: detectorConfig,
                        series_index: values.alertForm.config?.series_index ?? 0,
                        date_from:
                            values.simulationDateFrom ??
                            getDefaultSimulationRange(values.alertForm.calculation_interval),
                    })
                },
                clearSimulation: () => null,
            },
        ],
    })),

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
                    },
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
                    calculation_interval: insightIntervalToAlertInterval(props.insightInterval),
                    skip_weekend: false,
                    schedule_restriction: null,
                    detector_config: null,
                    insight: props.insightId,
                } as AlertFormType),
            errors: (alert: AlertType | AlertFormType) =>
                ({
                    name: !alert.name ? 'You need to give your alert a name' : undefined,
                    schedule_restriction: quietHoursFormError(alert.schedule_restriction),
                }) as DeepPartialMap<AlertType | AlertFormType, ValidationErrorType>,
            submit: async (alert) => {
                const payload: AlertTypeWrite = {
                    ...alert,
                    subscribed_users: alert.subscribed_users?.map(({ id }) => id),
                    insight: props.insightId,
                    // can only skip weekends for hourly/daily alerts
                    skip_weekend:
                        (alert.calculation_interval === AlertCalculationInterval.DAILY ||
                            alert.calculation_interval === AlertCalculationInterval.HOURLY) &&
                        alert.skip_weekend,
                    // can only check ongoing interval for absolute value/increase alerts with upper threshold
                    config: {
                        ...alert.config,
                        check_ongoing_interval: canCheckOngoingInterval(alert) && alert.config.check_ongoing_interval,
                    },
                    detector_config: alert.detector_config ?? null,
                    schedule_restriction:
                        (alert.schedule_restriction?.blocked_windows?.length ?? 0) > 0
                            ? alert.schedule_restriction
                            : null,
                }

                // absolute value alert can only have absolute threshold
                if (payload.condition.type === AlertConditionType.ABSOLUTE_VALUE) {
                    payload.threshold.configuration.type = InsightThresholdType.ABSOLUTE
                }

                const upsertToParent = (updatedAlert: AlertType): void => {
                    if (props.insightVizDataLogicProps) {
                        insightAlertsLogic({
                            insightId: props.insightId,
                            insightLogicProps: props.insightVizDataLogicProps,
                        }).actions.upsertAlert(updatedAlert)
                    }
                }

                // Must use alert.id (not the server-returned ID) to look up the logic instance where pending notifications were queued.
                // For new alerts alert.id is undefined, keying the logic as 'new' — using the server-returned ID would miss the queued state.
                const notifLogic = alertNotificationLogic({ alertId: alert.id })

                const flushPendingNotifications = async (savedAlertId: string): Promise<void> => {
                    if (notifLogic.values.pendingNotifications.length > 0) {
                        await notifLogic.asyncActions.createPendingHogFunctions(savedAlertId, alert.name)
                    }
                }

                try {
                    if (alert.id === undefined) {
                        const updatedAlert: AlertType = await api.alerts.create(payload)

                        await flushPendingNotifications(updatedAlert.id)
                        hydrateAlertLogicFromSaveResponse(updatedAlert)
                        lemonToast.success(`Alert created.`)
                        upsertToParent(updatedAlert)
                        props.onEditSuccess(updatedAlert.id)

                        return updatedAlert
                    }

                    const updatedAlert: AlertType = await api.alerts.update(alert.id, payload)

                    await flushPendingNotifications(updatedAlert.id)
                    hydrateAlertLogicFromSaveResponse(updatedAlert)
                    lemonToast.success(`Alert saved.`)
                    upsertToParent(updatedAlert)
                    props.onEditSuccess(updatedAlert.id)

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
        const getParentLogic = (): ReturnType<typeof insightAlertsLogic.build> | undefined => {
            if (props.insightVizDataLogicProps) {
                return insightAlertsLogic({
                    insightId: props.insightId,
                    insightLogicProps: props.insightVizDataLogicProps,
                })
            }
            return undefined
        }

        return {
            deleteAlert: async () => {
                if (!values.alertForm.id) {
                    throw new Error("Cannot delete alert that doesn't exist")
                }
                await api.alerts.delete(values.alertForm.id)
                lemonToast.success('Alert deleted.')
                const parent = getParentLogic()
                if (parent) {
                    parent.actions.removeAlert(values.alertForm.id)
                    parent.actions.loadAlerts()
                }
                props.onEditSuccess(undefined)
            },
            snoozeAlert: async ({ snoozeUntil }) => {
                if (!values.alertForm.id) {
                    throw new Error("Cannot snooze alert that doesn't exist")
                }
                const updatedAlert: AlertType = await api.alerts.update(values.alertForm.id, {
                    snoozed_until: snoozeUntil,
                })
                hydrateAlertLogicFromSaveResponse(updatedAlert)
                const parent = getParentLogic()
                if (parent) {
                    parent.actions.upsertAlert(updatedAlert)
                    parent.actions.loadAlerts()
                }
                props.onEditSuccess(values.alertForm.id)
            },
            clearSnooze: async () => {
                if (!values.alertForm.id) {
                    throw new Error("Cannot resolve alert that doesn't exist")
                }
                const updatedAlert: AlertType = await api.alerts.update(values.alertForm.id, {
                    snoozed_until: null,
                })
                hydrateAlertLogicFromSaveResponse(updatedAlert)
                const parent = getParentLogic()
                if (parent) {
                    parent.actions.upsertAlert(updatedAlert)
                    parent.actions.loadAlerts()
                }
                props.onEditSuccess(values.alertForm.id)
            },
            submitAlertFormSuccess: async () => {
                // Background sync to pick up any server-side changes
                getParentLogic()?.actions.loadAlerts()
            },
            simulateAlertSuccess: ({ simulationResult }) => {
                // simulateAlert returns null early for threshold alerts (no API call),
                // so null here means nothing actually ran — skip the event.
                if (simulationResult) {
                    const detectorConfig = values.alertForm.detector_config
                    const isBreakdown = Boolean(
                        simulationResult.breakdown_results && simulationResult.breakdown_results.length > 0
                    )
                    const totalPoints = isBreakdown
                        ? (simulationResult.breakdown_results?.reduce((sum, br) => sum + br.total_points, 0) ?? 0)
                        : simulationResult.total_points
                    const anomalyCount = isBreakdown
                        ? (simulationResult.breakdown_results?.reduce((sum, br) => sum + br.anomaly_count, 0) ?? 0)
                        : simulationResult.anomaly_count
                    posthog.capture('alert simulation run', {
                        success: true,
                        detector_type: detectorConfig?.type ?? null,
                        ensemble_operator: detectorConfig?.type === 'ensemble' ? detectorConfig.operator : null,
                        date_from:
                            values.simulationDateFrom ??
                            getDefaultSimulationRange(values.alertForm.calculation_interval),
                        anomaly_count: anomalyCount,
                        total_points: totalPoints,
                        is_breakdown: isBreakdown,
                    })
                }

                const parent = getParentLogic()
                if (!parent || !simulationResult) {
                    return
                }

                let anomalyPoints: AnomalyPoint[]

                if (simulationResult.breakdown_results && simulationResult.breakdown_results.length > 0) {
                    // For breakdowns, create anomaly points per breakdown value.
                    // Each breakdown result maps to a chart series by its position in the results array.
                    anomalyPoints = simulationResult.breakdown_results.flatMap((br, seriesIndex) =>
                        br.triggered_indices.map((idx) => ({
                            index: idx,
                            date: br.dates[idx] ?? '',
                            score: br.scores[idx] ?? null,
                            seriesIndex,
                        }))
                    )
                } else {
                    const seriesIndex = values.alertForm.config?.series_index ?? 0
                    anomalyPoints = simulationResult.triggered_indices.map((idx) => ({
                        index: idx,
                        date: simulationResult.dates[idx] ?? '',
                        score: simulationResult.scores[idx] ?? null,
                        seriesIndex,
                    }))
                }

                parent.actions.setSimulationAnomalyPoints(anomalyPoints)
            },
            simulateAlertFailure: ({ error }) => {
                const detectorConfig = values.alertForm.detector_config
                posthog.capture('alert simulation run', {
                    success: false,
                    detector_type: detectorConfig?.type ?? null,
                    ensemble_operator: detectorConfig?.type === 'ensemble' ? detectorConfig.operator : null,
                    date_from:
                        values.simulationDateFrom ?? getDefaultSimulationRange(values.alertForm.calculation_interval),
                    error: error ?? 'Unknown error',
                })
                lemonToast.error(`Simulation failed: ${error || 'Unknown error'}`)
            },
        }
    }),
])
