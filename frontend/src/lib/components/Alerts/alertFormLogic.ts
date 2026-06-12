import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { tryShowMCPHint } from 'lib/components/MCPHint/mcpHintLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { userLogic } from 'scenes/userLogic'

import {
    AlertCalculationInterval,
    AlertConditionType,
    GoalLine,
    InsightThresholdType,
    InsightsThresholdBounds,
} from '~/queries/schema/schema-general'
import { AvailableFeature, InsightLogicProps, IntervalType, QueryBasedInsightModel } from '~/types'

import {
    blockSubmitWithoutHighFrequencyAlertsEntitlement,
    getDefaultSimulationRange,
    HIGH_FREQUENCY_ALERTS_REQUIRED_MESSAGE,
    isHighFrequencyAlertInterval,
} from 'products/alerts/frontend/logic/alertIntervalHelpers'

import type { alertFormLogicType } from './alertFormLogicType'
import { getAlertFormValidationErrors } from './alertFormSchema'
import { alertLogic } from './alertLogic'
import { alertNotificationLogic } from './alertNotificationLogic'
import { insightAlertsLogic } from './insightAlertsLogic'
import {
    AlertConfig,
    AlertSimulationResult,
    AlertType,
    AlertTypeWrite,
    AnomalyPoint,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
} from './types'

export { THRESHOLD_BOUNDS_FORM_ERROR, thresholdAlertHasBounds } from './alertFormSchema'

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
    | 'investigation_agent_enabled'
    | 'investigation_gates_notifications'
    | 'investigation_inconclusive_action'
> & {
    id?: AlertType['id']
    created_by?: AlertType['created_by'] | null
    insight?: QueryBasedInsightModel['id']
}

export function canCheckOngoingInterval(alert?: AlertType | AlertFormType): boolean {
    const upper = alert?.threshold?.configuration?.bounds?.upper
    return (
        (alert?.condition?.type === AlertConditionType.ABSOLUTE_VALUE ||
            alert?.condition?.type === AlertConditionType.RELATIVE_INCREASE) &&
        upper != null &&
        !isNaN(upper)
    )
}

/** Mirror of the backend's ANY_ROW_MAX_ROWS — equality is pinned by a backend test. */
export const HOGQL_ANY_ROW_MAX_ROWS = 1000

/** One result row as the alert would read it, for the configure-time preview table. */
export interface HogQLAlertPreviewRow {
    /** Label-column value, falling back to the row number — mirrors the backend's row labeling. */
    label: string
    value: number | null
    breaching: boolean
}

/** What a SQL alert would evaluate right now, mirroring the backend extractor's column
 * resolution and shape checks so problems surface at configure time, not at the first check.
 * This is the advisory half of the PREVIEW MIRROR CONTRACT — the rule inventory lives on
 * `HogQLExtractor` in products/alerts/backend/evaluation/hogql.py; any rule change there must
 * land here and in both test suites. */
export type HogQLAlertPreview =
    | { status: 'no-rows' }
    | { status: 'bad-shape' }
    | { status: 'too-many-rows'; rowCount: number }
    | { status: 'ambiguous-columns'; columnNames: string[] | null }
    | { status: 'missing-column'; column: string; columnNames: string[] | null }
    | { status: 'not-numeric'; value: string }
    | {
          status: 'ok'
          mode: 'last_row' | 'any_row'
          /** Resolved evaluated column name; null when the result has no column metadata. */
          columnName: string | null
          /** Resolved label column name; null when rows are labeled by row number. */
          labelColumnName: string | null
          currentValue: number
          previousValue: number | null
          rowCount: number
          /** Rows whose value breaches the current absolute bounds; null when not computable. */
          breachingRows: number | null
          rows: HogQLAlertPreviewRow[]
      }

const _cellValue = (row: unknown, index: number): number | null => {
    if (!Array.isArray(row) || index >= row.length) {
        return null
    }
    const cell = row[index]
    if (cell === null) {
        return 0 // None buckets evaluate as 0, matching the backend
    }
    return typeof cell === 'number' && Number.isFinite(cell) ? cell : null
}

/** Mirror of the backend heuristic: a column is numeric by its most recent non-null value. */
const _columnIsNumeric = (rows: unknown[], index: number): boolean => {
    for (let i = rows.length - 1; i >= 0; i--) {
        const row = rows[i]
        if (!Array.isArray(row) || index >= row.length) {
            return false
        }
        const cell = row[index]
        if (cell === null) {
            continue
        }
        return typeof cell === 'number' && Number.isFinite(cell)
    }
    return false
}

export function deriveHogQLAlertPreview(
    insightData: Record<string, any> | null,
    config: AlertConfig | null | undefined,
    bounds: InsightsThresholdBounds | null | undefined
): HogQLAlertPreview | null {
    const rows = insightData?.result
    if (!Array.isArray(rows)) {
        return null // No result loaded yet — fall back to the static hint
    }
    if (rows.length === 0) {
        return { status: 'no-rows' }
    }
    const lastRow = rows[rows.length - 1]
    if (!Array.isArray(lastRow)) {
        return { status: 'bad-shape' }
    }

    const hogqlConfig = isHogQLAlertConfig(config) ? config : null
    const mode = hogqlConfig?.evaluation ?? 'last_row'
    if (mode === 'any_row' && rows.length > HOGQL_ANY_ROW_MAX_ROWS) {
        return { status: 'too-many-rows', rowCount: rows.length }
    }
    const columnNames = Array.isArray(insightData?.columns) ? insightData.columns.map(String) : null

    // Resolve the evaluated column the way the backend does: explicit pick, single column,
    // or the single numeric column — anything else needs the user to choose.
    let valueIndex: number
    if (hogqlConfig?.column != null) {
        const index = columnNames?.indexOf(hogqlConfig.column) ?? -1
        if (index < 0) {
            return { status: 'missing-column', column: hogqlConfig.column, columnNames }
        }
        valueIndex = index
    } else if (lastRow.length === 1) {
        valueIndex = 0
    } else {
        const numericIndexes = Array.from({ length: lastRow.length }, (_, i) => i).filter((i) =>
            _columnIsNumeric(rows, i)
        )
        if (numericIndexes.length !== 1) {
            return { status: 'ambiguous-columns', columnNames }
        }
        valueIndex = numericIndexes[0]
    }

    const currentValue = _cellValue(lastRow, valueIndex)
    if (currentValue === null) {
        return { status: 'not-numeric', value: String(lastRow[valueIndex]) }
    }

    // Label column: explicit pick, else the first non-evaluated column (e.g. the GROUP BY key).
    let labelIndex: number | null = null
    if (hogqlConfig?.label_column != null) {
        const index = columnNames?.indexOf(hogqlConfig.label_column) ?? -1
        if (index < 0) {
            return { status: 'missing-column', column: hogqlConfig.label_column, columnNames }
        }
        labelIndex = index
    } else if (lastRow.length > 1) {
        labelIndex = Array.from({ length: lastRow.length }, (_, i) => i).find((i) => i !== valueIndex) ?? null
    }

    // Per-row view (and backtest): with absolute bounds, mark which rows would breach right now.
    const hasBounds = !!bounds && (bounds.lower != null || bounds.upper != null)
    const previewRows: HogQLAlertPreviewRow[] = rows.map((row, i) => {
        const value = _cellValue(row, valueIndex)
        const labelCell = labelIndex !== null && Array.isArray(row) && labelIndex < row.length ? row[labelIndex] : null
        return {
            label: labelCell != null ? String(labelCell) : `row ${i + 1}`,
            value,
            breaching:
                hasBounds &&
                value !== null &&
                ((bounds.lower != null && value < bounds.lower) || (bounds.upper != null && value > bounds.upper)),
        }
    })

    const previousValue = rows.length > 1 ? _cellValue(rows[rows.length - 2], valueIndex) : null
    return {
        status: 'ok',
        mode,
        columnName: columnNames?.[valueIndex] ?? null,
        labelColumnName: labelIndex !== null ? (columnNames?.[labelIndex] ?? null) : null,
        currentValue,
        previousValue,
        rowCount: rows.length,
        breachingRows: hasBounds ? previewRows.filter((row) => row.breaching).length : null,
        rows: previewRows,
    }
}

export interface AlertFormLogicProps {
    alert: AlertType | null
    insightId: QueryBasedInsightModel['id']
    onEditSuccess: (alertId?: AlertType['id']) => void
    insightVizDataLogicProps?: InsightLogicProps
    insightInterval?: IntervalType
    /** Selects the default config type for new alerts based on the insight's query kind. */
    insightAlertKind?: 'hogql' | 'funnels' | 'trends'
}

const defaultConfigForInsight = (kind: AlertFormLogicProps['insightAlertKind']): AlertConfig => {
    if (kind === 'hogql') {
        return { type: 'HogQLAlertConfig' }
    }
    if (kind === 'funnels') {
        return { type: 'FunnelsAlertConfig', funnel_step: null, metric: 'conversion_from_start' }
    }
    return {
        type: 'TrendsAlertConfig',
        series_index: 0,
        check_ongoing_interval: false,
    }
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
function hydrateAlertLogicFromSaveResponse(updatedAlert: AlertType): void {
    const logic = alertLogic({ alertId: updatedAlert.id })
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

function alertToFormType(alert: AlertType, insightId: QueryBasedInsightModel['id']): AlertFormType {
    return {
        ...alert,
        insight: insightId,
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
        values: [
            trendsDataLogic({ dashboardId: undefined, ...props.insightVizDataLogicProps }),
            ['goalLines'],
            insightVizDataLogic({ dashboardItemId: undefined, ...props.insightVizDataLogicProps }),
            ['insightData'],
        ],
    })),

    actions({
        deleteAlert: true,
        snoozeAlert: (snoozeUntil: string) => ({ snoozeUntil }),
        clearSnooze: true,
        simulateAlert: true,
        clearSimulation: true,
        setSimulationDateFrom: (dateFrom: string) => ({ dateFrom }),
        setAlertFormSubmitAttempted: true,
    }),

    reducers({
        simulationDateFrom: [
            null as string | null,
            {
                setSimulationDateFrom: (_, { dateFrom }) => dateFrom,
            },
        ],
        alertFormSubmitAttempted: [
            false,
            {
                setAlertFormSubmitAttempted: () => true,
                submitAlertFormSuccess: () => false,
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
                    const formConfig = values.alertForm.config
                    return await api.alerts.simulate({
                        insight: props.insightId,
                        detector_config: detectorConfig,
                        series_index: isTrendsAlertConfig(formConfig) ? formConfig.series_index : 0,
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
            defaults: props.alert
                ? alertToFormType(props.alert, props.insightId)
                : ({
                      id: undefined,
                      name:
                          values.goalLines && values.goalLines.length > 0 ? `Crossed ${values.goalLines[0].label}` : '',
                      created_by: null,
                      created_at: '',
                      enabled: true,
                      config: defaultConfigForInsight(props.insightAlertKind),
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
                      investigation_agent_enabled: false,
                      investigation_gates_notifications: false,
                      investigation_inconclusive_action: 'notify',
                      insight: props.insightId,
                  } as AlertFormType),
            errors: (alert: AlertFormType) => getAlertFormValidationErrors(alert),
            submit: async (alert) => {
                if (
                    blockSubmitWithoutHighFrequencyAlertsEntitlement(
                        alert.calculation_interval,
                        userLogic.values.hasAvailableFeature(AvailableFeature.HIGH_FREQUENCY_ALERTS)
                    )
                ) {
                    lemonToast.error(HIGH_FREQUENCY_ALERTS_REQUIRED_MESSAGE)
                    throw new Error(HIGH_FREQUENCY_ALERTS_REQUIRED_MESSAGE)
                }

                const payload: AlertTypeWrite = {
                    ...alert,
                    subscribed_users: alert.subscribed_users?.map(({ id }) => id),
                    insight: props.insightId,
                    // can only skip weekends for sub-daily alerts
                    skip_weekend:
                        (alert.calculation_interval === AlertCalculationInterval.DAILY ||
                            isHighFrequencyAlertInterval(alert.calculation_interval)) &&
                        alert.skip_weekend,
                    // can only check ongoing interval for absolute value/increase alerts with upper threshold
                    config: isTrendsAlertConfig(alert.config)
                        ? {
                              ...alert.config,
                              check_ongoing_interval:
                                  canCheckOngoingInterval(alert) && alert.config.check_ongoing_interval,
                          }
                        : alert.config,
                    detector_config: alert.detector_config ?? null,
                    // Investigation agent only applies to anomaly (detector-based) alerts — force off otherwise.
                    investigation_agent_enabled: alert.detector_config
                        ? (alert.investigation_agent_enabled ?? false)
                        : false,
                    // Notification gating requires the investigation agent to be on.
                    investigation_gates_notifications:
                        alert.detector_config && alert.investigation_agent_enabled
                            ? (alert.investigation_gates_notifications ?? false)
                            : false,
                    investigation_inconclusive_action: alert.investigation_inconclusive_action ?? 'notify',
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
                    hydrateAlertLogicFromSaveResponse(updatedAlert)
                    upsertToParent(updatedAlert)
                    props.onEditSuccess(updatedAlert.id)
                } catch (postSaveError) {
                    posthog.captureException(postSaveError)
                }

                lemonToast.success(alert.id === undefined ? 'Alert created.' : 'Alert saved.')
                if (alert.id === undefined) {
                    tryShowMCPHint('alerts.create', {
                        derivedPrompt: alert.name ? `Create an alert called ${alert.name}` : undefined,
                    })
                }

                return alertToFormType(updatedAlert, props.insightId)
            },
        },
    })),

    selectors(({ props }) => ({
        thresholdBoundsFormError: [
            (s) => [s.alertFormSubmitAttempted, s.alertFormErrors],
            (submitAttempted, alertFormErrors): string | undefined => {
                if (!submitAttempted) {
                    return undefined
                }
                const thresholdError = alertFormErrors.threshold
                return typeof thresholdError === 'string' ? thresholdError : undefined
            },
        ],
        hogqlAlertPreview: [
            // Inputs are narrowed to the fields the preview reads, so name/interval/etc. keystrokes
            // don't re-derive it (the per-row map can cover up to 1000 rows).
            (s) => [
                s.insightData,
                (state, logicProps) => s.alertForm(state, logicProps)?.config,
                (state, logicProps) => s.alertForm(state, logicProps)?.threshold?.configuration?.bounds,
            ],
            (
                insightData: Record<string, any> | null,
                config: AlertConfig | null | undefined,
                bounds: InsightsThresholdBounds | null | undefined
            ): HogQLAlertPreview | null =>
                props.insightAlertKind === 'hogql' ? deriveHogQLAlertPreview(insightData, config, bounds) : null,
        ],
        /** Result column names of the SQL insight, for the column pickers. */
        hogqlResultColumns: [
            (s) => [s.insightData],
            (insightData): string[] | null =>
                props.insightAlertKind === 'hogql' && Array.isArray(insightData?.columns)
                    ? insightData.columns.map(String)
                    : null,
        ],
    })),

    listeners(({ props, values, actions }) => {
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
            submitAlertForm: () => {
                actions.setAlertFormSubmitAttempted()
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
                    const formConfig = values.alertForm.config
                    const seriesIndex = isTrendsAlertConfig(formConfig) ? formConfig.series_index : 0
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

    subscriptions(({ values, actions }) => ({
        // Materialize the heuristic-resolved evaluated column into the form, so the picker
        // shows the actual choice and the saved config is explicit. A subscription (not a
        // listener) because the preview derives from another logic's loader — there is no
        // single action to listen to. Only fires when the picker is visible (>1 column);
        // single-column queries stay implicit so they keep working if the column is renamed.
        hogqlAlertPreview: (preview: HogQLAlertPreview | null) => {
            const config = values.alertForm?.config
            if (
                preview?.status === 'ok' &&
                preview.columnName != null &&
                isHogQLAlertConfig(config) &&
                config.column == null &&
                (values.hogqlResultColumns?.length ?? 0) > 1
            ) {
                actions.setAlertFormValue('config', { ...config, column: preview.columnName })
            }
        },
    })),
])
