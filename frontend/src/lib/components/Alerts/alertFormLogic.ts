import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { tryShowMCPHint } from 'lib/components/MCPHint/mcpHintLogic'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { userLogic } from 'scenes/userLogic'

import {
    AlertCalculationInterval,
    AlertConditionType,
    GoalLine,
    HogQLAlertConfig,
    InsightThresholdType,
    InsightsThresholdBounds,
} from '~/queries/schema/schema-general'
import { AvailableFeature, InsightLogicProps, IntervalType, QueryBasedInsightModel } from '~/types'

import {
    blockSubmitWithoutEntitlement,
    getDefaultSimulationRange,
    isSubDailyAlertInterval,
} from 'products/alerts/frontend/logic/alertIntervalHelpers'

import type { alertFormLogicType } from './alertFormLogicType'
import { getAlertFormValidationErrors } from './alertFormSchema'
import { alertLogic } from './alertLogic'
import { alertNotificationLogic } from './alertNotificationLogic'
import { deriveFunnelAlertPreview, FunnelAlertPreview } from './funnelAlertPreview'
import { columnIsNumeric, deriveHogQLAlertPreview, HogQLAlertPreview } from './hogqlAlertPreview'
import { insightAlertsLogic } from './insightAlertsLogic'
import {
    AlertConfig,
    AlertSimulationResult,
    AlertType,
    AlertTypeWrite,
    AnomalyPoint,
    isFunnelsAlertConfig,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
    supportsOngoingInterval,
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

export function canCheckOngoingInterval(
    alert?: AlertType | AlertFormType,
    { isTrendsFunnel = false }: { isTrendsFunnel?: boolean } = {}
): boolean {
    // A funnel conversion rate isn't biased low over a partial period, so a trends funnel can always
    // check the ongoing one (steps funnels have no periods). A trends count is cumulative, so it's only
    // safe for an absolute/increase check above an upper bound.
    if (isFunnelsAlertConfig(alert?.config)) {
        return isTrendsFunnel
    }
    const upper = alert?.threshold?.configuration?.bounds?.upper
    return (
        (alert?.condition?.type === AlertConditionType.ABSOLUTE_VALUE ||
            alert?.condition?.type === AlertConditionType.RELATIVE_INCREASE) &&
        upper != null &&
        !isNaN(upper)
    )
}

const ONGOING_DISABLED_REASON =
    'Can only alert for ongoing period when checking for absolute value/increase above a set upper threshold.'
const ONGOING_TOOLTIP_FUNNEL =
    'By default the alert uses the most recently completed period. Enable this to evaluate the current, still-in-progress period instead — useful to be alerted sooner, at the cost of a partial datapoint.'
const ONGOING_TOOLTIP_TRENDS =
    "Checks the insight value for the ongoing period (current week/month) that hasn't yet completed. Use this if you want to be alerted right away when the insight value rises/increases above threshold"

export interface OngoingIntervalField {
    show: boolean
    checked: boolean
    disabledReason?: string
    tooltip: string
}

/** State of the "Check ongoing period" advanced-option, keyed on alert kind — so the per-kind
 * branching lives here rather than growing inside the component as more alert types are added. */
export function ongoingIntervalField(config: AlertConfig | null | undefined, canCheck: boolean): OngoingIntervalField {
    return {
        // Trends alerts show the toggle even when ineligible (disabled); funnels only when eligible.
        show: supportsOngoingInterval(config) && (isTrendsAlertConfig(config) || canCheck),
        checked: supportsOngoingInterval(config) && !!config.check_ongoing_interval && canCheck,
        disabledReason: canCheck ? undefined : ONGOING_DISABLED_REASON,
        tooltip: isFunnelsAlertConfig(config) ? ONGOING_TOOLTIP_FUNNEL : ONGOING_TOOLTIP_TRENDS,
    }
}

/** The insight query kind an alert is built for; selects the default config type for new alerts. */
export type InsightAlertKind = 'trends' | 'hogql' | 'funnels'

export interface AlertFormLogicProps {
    alert: AlertType | null
    insightId: QueryBasedInsightModel['id']
    onEditSuccess: (alertId?: AlertType['id']) => void
    insightVizDataLogicProps?: InsightLogicProps
    insightInterval?: IntervalType
    /** Selects the default config type for new alerts based on the insight's query kind. */
    insightAlertKind?: InsightAlertKind
    /** For funnel insights: whether it's a trends (historical) funnel, which alerts on the overall
     * conversion rate over time rather than a single step snapshot. Drives the preview shape. */
    insightIsTrendsFunnel?: boolean
}

const defaultConfigForInsight = (kind: AlertFormLogicProps['insightAlertKind']): AlertConfig => {
    if (kind === 'hogql') {
        // last_row is the default — the most common SQL alert shape is a chronological series.
        return { type: 'HogQLAlertConfig', evaluation: 'last_row' }
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
                        // SQL insights have no series_index; the config carries the evaluated column
                        // and read direction so the preview matches what the alert will score.
                        config: formConfig,
                    })
                },
                clearSimulation: () => null,
            },
        ],
    })),

    forms(({ props, values, actions }) => ({
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
                const entitlementCheck = blockSubmitWithoutEntitlement(alert.calculation_interval, {
                    hasHighFrequencyAlertsEntitlement: userLogic.values.hasAvailableFeature(
                        AvailableFeature.HIGH_FREQUENCY_ALERTS
                    ),
                    hasRealTimeAlertsEntitlement: userLogic.values.hasAvailableFeature(
                        AvailableFeature.REAL_TIME_ALERTS
                    ),
                })
                if (entitlementCheck.blocked) {
                    upgradeModalLogic.actions.setUpgradeModalFeatureKey(entitlementCheck.feature)
                    actions.setAlertFormManualErrors({ calculation_interval: entitlementCheck.message })
                    throw new Error(entitlementCheck.message)
                }

                const payload: AlertTypeWrite = {
                    ...alert,
                    subscribed_users: alert.subscribed_users?.map(({ id }) => id),
                    insight: props.insightId,
                    // can only skip weekends for sub-daily alerts
                    skip_weekend:
                        (alert.calculation_interval === AlertCalculationInterval.DAILY ||
                            isSubDailyAlertInterval(alert.calculation_interval)) &&
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
                // Funnels express relative change as a percentage of the prior period; the absolute (#)
                // unit is hidden in the funnel UI, so persist PERCENTAGE for any funnel relative condition.
                if (
                    isFunnelsAlertConfig(payload.config) &&
                    payload.condition.type !== AlertConditionType.ABSOLUTE_VALUE
                ) {
                    payload.threshold.configuration.type = InsightThresholdType.PERCENTAGE
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
            // don't re-derive it (the per-row map can cover up to HOGQL_ANY_ROW_MAX_ROWS rows).
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
        /** The conversion rate(s) a funnel alert would evaluate right now, with breach status; null until the result loads. */
        funnelAlertPreview: [
            (s) => [
                s.insightData,
                (state, logicProps) => s.alertForm(state, logicProps)?.config,
                (state, logicProps) => s.alertForm(state, logicProps)?.threshold?.configuration?.bounds,
                (state, logicProps) => s.alertForm(state, logicProps)?.condition?.type,
                (state, logicProps) => s.alertForm(state, logicProps)?.threshold?.configuration?.type,
            ],
            (
                insightData: Record<string, any> | null,
                config: AlertConfig | null | undefined,
                bounds: InsightsThresholdBounds | null | undefined,
                conditionType: AlertConditionType | undefined,
                thresholdType: InsightThresholdType | undefined
            ): FunnelAlertPreview | null =>
                props.insightAlertKind === 'funnels'
                    ? deriveFunnelAlertPreview(
                          insightData,
                          config,
                          bounds,
                          !!props.insightIsTrendsFunnel,
                          conditionType,
                          thresholdType
                      )
                    : null,
        ],
        /** Result column names of the SQL insight, for the column pickers. */
        hogqlResultColumns: [
            (s) => [s.insightData],
            (insightData): string[] | null =>
                props.insightAlertKind === 'hogql' && Array.isArray(insightData?.columns)
                    ? insightData.columns.map(String)
                    : null,
        ],
        /** Result columns with numeric cells — the only valid picks for the evaluated column. */
        hogqlNumericColumns: [
            (s) => [s.insightData, s.hogqlResultColumns],
            (insightData, resultColumns): string[] | null =>
                resultColumns && Array.isArray(insightData?.result)
                    ? resultColumns.filter((_, index) => columnIsNumeric(insightData.result, index))
                    : null,
        ],
        /** Default evaluated column for the picker: the last numeric column (SQL convention puts
         * the measure last). Bolder than the backend's single-numeric fallback because the user
         * sees the prefilled pick and it's stored explicitly. Null when the picker is hidden
         * (single-column results) or nothing numeric is detectable. */
        hogqlSuggestedColumn: [
            (s) => [s.hogqlResultColumns, s.hogqlNumericColumns],
            (resultColumns, numericColumns): string | null =>
                (resultColumns?.length ?? 0) > 1 && numericColumns && numericColumns.length > 0
                    ? numericColumns[numericColumns.length - 1]
                    : null,
        ],
        /** Unset SQL config fields to materialize: the evaluated column (last numeric) and the
         * label (first column that isn't evaluated — the backend fallback). Both apply in every
         * evaluation mode: the label names the evaluated row(s) in breach messages regardless of
         * last/first/any-row. Computed together so prefilling lands in a single form write with
         * no ordering between the fields. Null when there's nothing to fill. */
        hogqlConfigPrefill: [
            (s) => [
                s.hogqlResultColumns,
                s.hogqlSuggestedColumn,
                (state, logicProps) => s.alertForm(state, logicProps)?.config,
            ],
            (
                resultColumns: string[] | null,
                suggestedColumn: string | null,
                config: AlertConfig | null | undefined
            ): Partial<Pick<HogQLAlertConfig, 'column' | 'label_column'>> | null => {
                if (!isHogQLAlertConfig(config)) {
                    return null
                }
                const patch: Partial<Pick<HogQLAlertConfig, 'column' | 'label_column'>> = {}
                if (config.column == null && suggestedColumn != null) {
                    patch.column = suggestedColumn
                }
                const evaluated = config.column ?? suggestedColumn
                if (config.label_column == null && evaluated != null) {
                    const label = resultColumns?.find((column) => column !== evaluated)
                    if (label != null) {
                        patch.label_column = label
                    }
                }
                return Object.keys(patch).length > 0 ? patch : null
            },
        ],
        /** Options for the evaluated-column picker: the numeric columns. Falls back to every
         * column when the result isn't loaded or nothing numeric was detected — an empty
         * picker would be a dead end. A stored pick missing from the options still renders
         * on the select button, but can't be re-picked. */
        hogqlValueColumnOptions: [
            (s) => [s.hogqlResultColumns, s.hogqlNumericColumns],
            (resultColumns: string[] | null, numericColumns: string[] | null): { label: string; value: string }[] => {
                const columns =
                    numericColumns === null || numericColumns.length === 0 ? (resultColumns ?? []) : numericColumns
                return columns.map((column) => ({ label: column, value: column }))
            },
        ],
        /** Options for the label-column picker: every column except the evaluated one. */
        hogqlLabelColumnOptions: [
            (s) => [s.hogqlResultColumns, (state, logicProps) => s.alertForm(state, logicProps)?.config],
            (
                resultColumns: string[] | null,
                config: AlertConfig | null | undefined
            ): { label: string; value: string }[] => {
                const evaluated = isHogQLAlertConfig(config) ? (config.column ?? null) : null
                return (resultColumns ?? [])
                    .filter((column) => column !== evaluated)
                    .map((column) => ({ label: column, value: column }))
            },
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

    subscriptions(({ props, values, actions }) =>
        // Create-only: prefilling an existing alert would dirty the form on passive open and,
        // if the query result shape drifted since save, silently rewrite a stored column. New
        // alerts have nothing to clobber. A subscription (not a listener) because the suggestion
        // derives from another logic's loader — there is no single action to listen to. Never
        // fires for single-column results (picker hidden there); those stay implicit so they
        // keep working on column renames.
        props.insightAlertKind !== 'hogql' || props.alert
            ? {}
            : {
                  // Materialize the suggested picks into the form, so the pickers show the actual
                  // choice and the saved config is explicit.
                  hogqlConfigPrefill: (patch: Partial<Pick<HogQLAlertConfig, 'column' | 'label_column'>> | null) => {
                      const config = values.alertForm?.config
                      if (patch != null && isHogQLAlertConfig(config)) {
                          actions.setAlertFormValue('config', { ...config, ...patch })
                      }
                  },
              }
    ),
])
