import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { AlertConditionType, BreakdownFilter, GoalLine, InsightThresholdType } from '~/queries/schema/schema-general'
import {
    containsHogQLQuery,
    hasBreakdownFilter,
    isFunnelsQuery,
    isInsightVizNode,
    isMetricsQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { FunnelVizType, InsightLogicProps } from '~/types'

import type { FeatureFlagsSet } from '../../../../frontend/src/lib/logic/featureFlagLogic'
import type { Node } from '../../../../frontend/src/queries/schema/schema-general'
import type { QueryBasedInsightModel } from '../../../../frontend/src/types'
import { AlertType, AnomalyPoint, isTrendsAlertConfig } from '../types'

export interface InsightAlertsLogicProps {
    insightId: number
    insightLogicProps: InsightLogicProps
    /**
     * When true, skip the afterMount alerts fetch. Used for dashboard tiles where `insight.alerts` is often an
     * unprefetched `[]` and we must not N+1 on mount. Call `loadAlerts()` when surfacing the UI that needs the list
     * (e.g. before `ManageAlertsModal` opens).
     */
    deferInitialAlertsLoad?: boolean
}

/** Per-kind feature-flag state threaded from call sites into the alert-support predicates. */
export interface AlertSupportFlagOptions {
    metricsAlertsEnabled?: boolean
}

export const areAlertsSupportedForInsight = (
    query?: Record<string, any> | null,
    options: AlertSupportFlagOptions = {}
): boolean => {
    if (!query) {
        return false
    }
    if (isInsightVizNode(query) && isTrendsQuery(query.source)) {
        return true
    }
    if (isInsightVizNode(query) && isFunnelsQuery(query.source)) {
        // Steps and trends both alert on a conversion-rate percentage. Time-to-convert (a duration)
        // and flow (a sankey) have no conversion-rate metric, so they aren't supported.
        const vizType = query.source.funnelsFilter?.funnelVizType
        return vizType !== FunnelVizType.TimeToConvert && vizType !== FunnelVizType.Flow
    }
    // Metrics insights persist a bare MetricsQuery node (no InsightVizNode wrapper).
    if (options.metricsAlertsEnabled && isMetricsQuery(query)) {
        return true
    }
    return containsHogQLQuery(query)
}

export const areAnomalyAlertsSupportedForInsight = (
    query?: Record<string, any> | null,
    options: AlertSupportFlagOptions = {}
): boolean => {
    if (!areAlertsSupportedForInsight(query, options)) {
        return false
    }
    if (query && isInsightVizNode(query) && isTrendsQuery(query.source)) {
        const display = query.source.trendsFilter?.display
        return !display || !NON_TIME_SERIES_DISPLAY_TYPES.includes(display)
    }
    return true
}

// List only the insight types this account can actually alert on — naming a flag-gated type the
// user doesn't have would disclose an unreleased feature.
const alertableInsightTypesLabel = (options: AlertSupportFlagOptions): string =>
    ['trends', 'SQL', 'funnel', options.metricsAlertsEnabled && 'metrics'].filter(Boolean).join(', ')

export const alertsUnsupportedReason = (
    options: AlertSupportFlagOptions,
    query?: Record<string, any> | null
): string => {
    // A funnel on a viz type without a conversion-rate metric otherwise reads as a contradiction —
    // "funnel insights are supported" while standing on a blocked funnel. Name the real reason instead.
    if (query && isInsightVizNode(query) && isFunnelsQuery(query.source)) {
        const vizType = query.source.funnelsFilter?.funnelVizType
        if (vizType === FunnelVizType.TimeToConvert || vizType === FunnelVizType.Flow) {
            return "Alerts track a conversion rate, which time-to-convert and flow funnels don't have. Switch to the steps or trends view to add an alert."
        }
    }
    return `Alerts are only available for ${alertableInsightTypesLabel(options)} insights. Change the insight representation to add alerts.`
}

/** Map absolute-threshold alerts to chart goal lines (shared by trends and SQL charts). */
export function alertsToThresholdGoalLines(alerts: AlertType[]): GoalLine[] {
    return alerts.flatMap((alert) => {
        if (
            alert.threshold.configuration.type !== InsightThresholdType.ABSOLUTE ||
            alert.condition.type !== AlertConditionType.ABSOLUTE_VALUE ||
            !alert.threshold.configuration.bounds
        ) {
            return []
        }

        const bounds = alert.threshold.configuration.bounds

        const annotations: GoalLine[] = []
        if (bounds.upper != null) {
            annotations.push({
                label: `${alert.name} Upper Threshold`,
                value: bounds.upper,
            })
        }

        if (bounds.lower != null) {
            annotations.push({
                label: `${alert.name} Lower Threshold`,
                value: bounds.lower,
            })
        }

        return annotations
    })
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface insightAlertsLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    insight: Partial<QueryBasedInsightModel<Node<Record<string, any>>>> // insightLogic
    breakdownFilter: BreakdownFilter | null | undefined // insightVizDataLogic
    showAlertThresholdLines: boolean | null | undefined // insightVizDataLogic
    alertAnomalyPoints: AnomalyPoint[]
    alertThresholdLines: GoalLine[]
    alerts: AlertType[]
    alertsLoading: boolean
    hasDetectorAlerts: boolean
    shouldShowAlertDeletionWarning: boolean
    showAlertAnomalyPointsFlag: boolean
    simulationAnomalyPoints: AnomalyPoint[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface insightAlertsLogicActions {
    setQuery: (query: Node<Record<string, any>> | null) => {
        query: Node<Record<string, any>> | null
    } // insightVizDataLogic
    clearSimulationAnomalyPoints: () => {
        value: true
    }
    loadAlerts: () => any
    loadAlertsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAlertsSuccess: (
        alerts: AlertType[],
        payload?: any
    ) => {
        alerts: AlertType[]
        payload?: any
    }
    removeAlert: (alertId: AlertType['id']) => {
        alertId: string
    }
    setShouldShowAlertDeletionWarning: (show: boolean) => {
        show: boolean
    }
    setShowAlertAnomalyPoints: (show: boolean) => {
        show: boolean
    }
    setSimulationAnomalyPoints: (points: AnomalyPoint[]) => {
        points: AnomalyPoint[]
    }
    upsertAlert: (alert: AlertType) => {
        alert: AlertType
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface insightAlertsLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        alertThresholdLines: (alerts: AlertType[], showAlertThresholdLines: boolean | null | undefined) => GoalLine[]
        hasDetectorAlerts: (alerts: AlertType[]) => boolean
        alertAnomalyPoints: (
            alerts: AlertType[],
            showAlertAnomalyPointsFlag: boolean,
            simulationAnomalyPoints: AnomalyPoint[],
            breakdownFilter: BreakdownFilter | null | undefined
        ) => AnomalyPoint[]
    }
}

export type insightAlertsLogicType = MakeLogicType<
    insightAlertsLogicValues,
    insightAlertsLogicActions,
    InsightAlertsLogicProps,
    insightAlertsLogicMeta
>

export const insightAlertsLogic = kea<insightAlertsLogicType>([
    path(['lib', 'components', 'Alerts', 'insightAlertsLogic']),
    props({} as InsightAlertsLogicProps),
    key(({ insightId }) => `insight-${insightId}`),
    actions({
        setShouldShowAlertDeletionWarning: (show: boolean) => ({ show }),
        upsertAlert: (alert: AlertType) => ({ alert }),
        removeAlert: (alertId: AlertType['id']) => ({ alertId }),
        setSimulationAnomalyPoints: (points: AnomalyPoint[]) => ({ points }),
        clearSimulationAnomalyPoints: true,
        setShowAlertAnomalyPoints: (show: boolean) => ({ show }),
    }),

    connect((props: InsightAlertsLogicProps) => ({
        actions: [insightVizDataLogic(props.insightLogicProps), ['setQuery']],
        values: [
            insightVizDataLogic(props.insightLogicProps),
            ['showAlertThresholdLines', 'breakdownFilter'],
            insightLogic(props.insightLogicProps),
            ['insight'],
        ],
    })),

    loaders(({ props }) => ({
        alerts: {
            __default: [] as AlertType[],
            loadAlerts: async () => {
                const response = await api.alerts.list(props.insightId)
                return response.results
            },
        },
    })),

    reducers({
        alerts: [
            [] as AlertType[],
            {
                upsertAlert: (state, { alert }) => {
                    const index = state.findIndex((a) => a.id === alert.id)
                    if (index >= 0) {
                        return [...state.slice(0, index), alert, ...state.slice(index + 1)]
                    }
                    return [...state, alert]
                },
                removeAlert: (state, { alertId }) => state.filter((a) => a.id !== alertId),
            },
        ],
        shouldShowAlertDeletionWarning: [
            false,
            {
                setShouldShowAlertDeletionWarning: (_, { show }) => show,
            },
        ],
        simulationAnomalyPoints: [
            [] as AnomalyPoint[],
            {
                setSimulationAnomalyPoints: (_, { points }) => points,
                clearSimulationAnomalyPoints: () => [],
            },
        ],
        showAlertAnomalyPointsFlag: [
            false,
            {
                setShowAlertAnomalyPoints: (_, { show }) => show,
            },
        ],
    }),

    selectors({
        alertThresholdLines: [
            (s) => [s.alerts, s.showAlertThresholdLines],
            (alerts: AlertType[], showAlertThresholdLines: boolean): GoalLine[] =>
                showAlertThresholdLines ? alertsToThresholdGoalLines(alerts) : [],
        ],
        /** Whether the insight has any detector-based alerts (used to show/hide the toggle). */
        hasDetectorAlerts: [
            (s) => [s.alerts],
            (alerts: AlertType[]): boolean => alerts.some((a) => !!a.detector_config),
        ],
        /** Anomaly points from the latest check of detector-based alerts, merged with any active simulation points. */
        alertAnomalyPoints: [
            (s) => [s.alerts, s.showAlertAnomalyPointsFlag, s.simulationAnomalyPoints, s.breakdownFilter],
            (
                alerts: AlertType[],
                showFlag: boolean,
                simulationPoints: AnomalyPoint[],
                breakdownFilter: BreakdownFilter | null
            ): AnomalyPoint[] => {
                // Simulation points take priority when active (user is previewing).
                // These already have correct per-breakdown seriesIndex from alertFormLogic.
                if (simulationPoints.length > 0) {
                    return simulationPoints
                }

                if (!showFlag) {
                    return []
                }

                const hasBreakdown = hasBreakdownFilter(breakdownFilter)

                // Derive from all firing checks of each detector-based alert.
                // Each check typically has 0-1 triggered points, so we aggregate
                // across checks to build the full anomaly timeline. Deduplicate by date.
                const seen = new Set<string>()
                return alerts.flatMap((alert) => {
                    if (!alert.detector_config || !alert.checks?.length) {
                        return []
                    }
                    const defaultSeriesIndex = isTrendsAlertConfig(alert.config) ? alert.config.series_index : 0
                    return alert.checks.flatMap((check) => {
                        if (!check.triggered_dates?.length) {
                            return []
                        }
                        // For breakdown alerts, use the stored series index from the check
                        // so the dot appears on the correct breakdown series.
                        // For non-breakdown alerts, fall back to the alert's series_index.
                        const seriesIndex =
                            hasBreakdown && check.triggered_metadata?.series_index != null
                                ? (check.triggered_metadata.series_index as number)
                                : defaultSeriesIndex
                        return check.triggered_dates
                            .filter((date) => {
                                const key = `${seriesIndex}:${date}`
                                if (seen.has(key)) {
                                    return false
                                }
                                seen.add(key)
                                return true
                            })
                            .map((date, i) => {
                                const ptIdx = check.triggered_points?.[i] ?? 0
                                const scores = check.anomaly_scores
                                // Score array may be shorter than the point index (e.g. detect() returns single score)
                                const score =
                                    scores && ptIdx < scores.length
                                        ? scores[ptIdx]
                                        : (scores?.[scores.length - 1] ?? null)
                                return { index: ptIdx, date, score, seriesIndex }
                            })
                    })
                })
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setQuery: ({ query }) => {
            if (values.alerts.length === 0 || areAlertsSupportedForInsight(query)) {
                actions.setShouldShowAlertDeletionWarning(false)
            } else {
                actions.setShouldShowAlertDeletionWarning(true)
            }
        },
        setShowAlertAnomalyPoints: ({ show }) => {
            // When toggling on, reload alerts from the API to get latest check data
            // (inline alerts from the insight endpoint don't include checks)
            if (show && values.alerts.some((a) => !!a.detector_config && !a.checks?.length)) {
                actions.loadAlerts()
            }
        },
    })),

    afterMount(({ actions, values, props }) => {
        if (props.deferInitialAlertsLoad) {
            return
        }
        // If the insight has an alerts property (even if empty), use it - this means the backend sent us the alerts data
        if (values.insight?.alerts && Array.isArray(values.insight.alerts)) {
            actions.loadAlertsSuccess(values.insight.alerts)
        } else {
            // No alerts property means we need to fetch from API (e.g., when viewing insight in isolation)
            actions.loadAlerts()
        }
    }),
])
