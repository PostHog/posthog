import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms, type DeepPartialMap, type ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
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
    /** Must match the `alertLogic` instance keyed on the same alertId — read from `useFeatureFlag('ALERTS_HISTORY_CHART')` in the parent. */
    historyChartEnabled: boolean
}

/**
 * Hydrate alertLogic from the save response, then kick off a background refetch so pagination-aware
 * `checks` / `checks_total` (which PATCH/POST bodies omit) catch up without blocking the UI.
 * Preserves the previously loaded `checks` state so the history section doesn't flash empty.
 *
 * On create, the alertLogic instance keyed by the newly minted id has never been mounted — reading
 * `logic.values` on an unmounted logic throws a `[KEA] Can not find path …` error. Check mount state
 * first and skip the merge (there's nothing to preserve for a brand-new alert).
 */
function hydrateAlertLogicFromSaveResponse(updatedAlert: AlertType, historyChartEnabled: boolean): void {
    const logic = alertLogic({ alertId: updatedAlert.id, historyChartEnabled })
    const wasMounted = logic.isMounted()
    const previousAlert = wasMounted ? logic.values.alert : null
    const savedChecks = updatedAlert.checks ?? []
    const mergedAlert: AlertType = {
        ...updatedAlert,
        checks: savedChecks.length > 0 ? savedChecks : (previousAlert?.checks ?? []),
        checks_total: updatedAlert.checks_total ?? previousAlert?.checks_total,
    }

    if (wasMounted) {
        logic.actions.loadAlertSuccess(mergedAlert)
        void logic.asyncActions.loadAlert()
        return
    }

    const unmount = logic.mount()
    logic.actions.loadAlertSuccess(mergedAlert)
    // On create, mounting triggers `afterMount`, which already loads the alert in the background.
    // Avoid a duplicate refetch here and clean up the temporary mount immediately after dispatching.
    unmount()
}

function formatSaveError(error: unknown): string {
    if (error instanceof ApiError) {
        const field = error.attr?.replace(/_/g, ' ')
        const detail = error.detail ?? error.message
        return field ? `${field}: ${detail}` : detail
    }
    if (error instanceof Error) {
        return error.message
    }
    return 'Unknown error'
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

                let updatedAlert: AlertType
                try {
                    updatedAlert =
                        alert.id === undefined
                            ? await api.alerts.create(payload)
                            : await api.alerts.update(alert.id, payload)
                } catch (error: unknown) {
                    // `AlertViewSet` is a standard DRF ModelViewSet, so validation errors arrive as
                    // `{attr, detail}`. Anything else (network blip, non-ApiError thrown somehow) shouldn't
                    // be formatted with those fields or we end up with "undefined: undefined".
                    lemonToast.error(`Error saving alert: ${formatSaveError(error)}`)
                    throw error
                }

                // The alert is already persisted — any error from the local side-effects below is a
                // client-side bug, not a save failure. Capture it for investigation but don't surface it
                // as "Error saving alert" since the API returned 2xx. Regression guarded by `alertFormLogic.test.ts`.
                try {
                    await flushPendingNotifications(updatedAlert.id)
                    hydrateAlertLogicFromSaveResponse(updatedAlert, props.historyChartEnabled)
                    upsertToParent(updatedAlert)
                    props.onEditSuccess(updatedAlert.id)
                } catch (postSaveError) {
                    posthog.captureException(postSaveError)
                }

                lemonToast.success(alert.id === undefined ? 'Alert created.' : 'Alert saved.')

                return updatedAlert
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
                hydrateAlertLogicFromSaveResponse(updatedAlert, props.historyChartEnabled)
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
                hydrateAlertLogicFromSaveResponse(updatedAlert, props.historyChartEnabled)
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
