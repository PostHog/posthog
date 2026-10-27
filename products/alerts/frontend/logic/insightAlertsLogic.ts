import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import {
    AlertConditionType,
    BreakdownFilter,
    GoalLine,
    TrendsQuery,
    FunnelsQuery,
    InsightThresholdType,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    containsHogQLQuery,
    hasBreakdownFilter,
    isFunnelsQuery,
    isInsightVizNode,
    isMetricsQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { FunnelVizType, InsightLogicProps } from '~/types'

import type { Node } from '../../../../frontend/src/queries/schema/schema-general'
import type {
    LifecycleQuery,
    PathsQuery,
    PathsV2Query,
    RetentionQuery,
    StickinessQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
} from '../../../../frontend/src/queries/schema/schema-general'
import type { InsightModel } from '../../../../frontend/src/types'
import { AlertType, AnomalyPoint, isFunnelsAlertConfig, isTrendsAlertConfig, isHogQLAlertConfig } from '../types'
import { buildAlertFilterConfig } from './alertNotifications'

export interface InsightAlertsLogicProps {
    insightId: number
    insightLogicProps: InsightLogicProps
    /**
     * When true, skip the afterMount alerts API fetch and the per-alert destination-count fetch — a dashboard
     * mounts one of these logics per tile, so those requests N+1 on load. Inline `insight.alerts` (prefetched by
     * the dashboard endpoints) still hydrates, so saved display options like alert threshold lines can render.
     * Call `loadAlerts()` when surfacing UI that needs fresh data (e.g. before `ManageAlertsModal` opens).
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
    // Matches the backend DETECTOR_EXTRACTORS, which rejects an anomaly alert on any kind but trends and SQL.
    return containsHogQLQuery(query)
}

const ALERT_SURVIVING_QUERY_KINDS: ReadonlySet<string> = new Set([
    NodeKind.TrendsQuery,
    NodeKind.HogQLQuery,
    NodeKind.FunnelsQuery,
    NodeKind.MetricsQuery,
])

// Matches the backend Insight.alertable_query_kind, which reads no flag or funnel viz when it deletes alerts on save.
const alertsSurviveQuery = (query?: Record<string, any> | null): boolean => {
    let node = query
    while (node?.source) {
        node = node.source
    }
    return !!node && ALERT_SURVIVING_QUERY_KINDS.has(node.kind)
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

export type AlertChartContext =
    | {
          query: TrendsQuery | FunnelsQuery
          results: {
              data?: (number | null)[]
              order?: number
              compare?: boolean
              compare_label?: 'current' | 'previous'
              count?: number
          }[]
      }
    | {
          columns: { name: string; dataIndex: number; type: { isNumerical: boolean } }[]
          rows: unknown[][]
          hasMore?: boolean
      }

function alertPreviousValue(alert: AlertType, context?: AlertChartContext): number | null {
    if (!context) {
        return null
    }
    if ('rows' in context) {
        if (!isHogQLAlertConfig(alert.config) || alert.config.evaluation === 'any_row') {
            return null
        }
        if (context.hasMore && alert.config.evaluation === 'last_row') {
            return null
        }
        const columnName = alert.config.column
        const candidates = context.columns.filter((column) =>
            columnName ? column.name === columnName : column.type.isNumerical
        )
        if (candidates.length !== 1 || context.rows.length < 2) {
            return null
        }
        const rowIndex = alert.config.evaluation === 'first_row' ? 1 : context.rows.length - 2
        const raw = context.rows[rowIndex]?.[candidates[0].dataIndex]
        const previous = raw == null ? null : Number(raw)
        return previous != null && Number.isFinite(previous) ? previous : null
    }
    if (isFunnelsQuery(context.query) && hasBreakdownFilter(context.query.breakdownFilter)) {
        return null
    }
    const seriesIndex = isTrendsAlertConfig(alert.config) ? alert.config.series_index : 0
    const currentResults = context.results.filter((result) => result.compare_label !== 'previous')
    const matchingResults = currentResults.filter((result, index) => (result.order ?? index) === seriesIndex)
    if (matchingResults.length !== 1) {
        return null
    }
    const data = matchingResults[0].data
    if (!Array.isArray(data)) {
        return null
    }
    const checkOngoing = 'check_ongoing_interval' in alert.config && alert.config.check_ongoing_interval
    const useLastPoint =
        context.query.dateRange?.excludeIncompletePeriods ||
        (checkOngoing &&
            (isFunnelsQuery(context.query) || alert.condition.type === AlertConditionType.RELATIVE_INCREASE))
    const anchor = data.length - (useLastPoint ? 1 : 2) - (alert.evaluation_delay_intervals ?? 0)
    const previous = data[anchor - 1]
    return previous != null && Number.isFinite(previous) ? previous : null
}

function funnelThresholdScale(alert: AlertType, context?: AlertChartContext): number | null {
    if (!context || 'rows' in context || !isFunnelsQuery(context.query) || !isFunnelsAlertConfig(alert.config)) {
        return 1
    }
    const { query, results } = context
    if (query.funnelsFilter?.funnelVizType === FunnelVizType.Trends) {
        return 1
    }
    if (hasBreakdownFilter(query.breakdownFilter)) {
        return null
    }
    const currentSteps = results.filter((result) => result.compare_label !== 'previous')
    const previousSteps = results.filter((result) => result.compare_label === 'previous')
    const step = alert.config.funnel_step ?? currentSteps.length - 1
    const alertBase = alert.config.metric === 'conversion_from_previous' ? step - 1 : 0
    let chartBase = 0
    if (query.funnelsFilter?.funnelStepReference === 'previous' && step > 0) {
        chartBase = step - 1
        while (chartBase > 0 && query.series[chartBase]?.optionalInFunnel) {
            chartBase--
        }
    }
    if (alertBase === chartBase && previousSteps.length === 0) {
        return 1
    }
    const alertCount = currentSteps[alertBase]?.count
    const chartCount =
        previousSteps.length > 0
            ? Math.max(currentSteps[0]?.count ?? 0, previousSteps[0]?.count ?? 0)
            : currentSteps[chartBase]?.count
    if (alertCount == null || chartCount == null || chartCount <= 0) {
        return null
    }
    return alertCount / chartCount
}

export function alertsToThresholdGoalLines(alerts: AlertType[], context?: AlertChartContext): GoalLine[] {
    return alerts.flatMap((alert) => {
        const { bounds, type } = alert.threshold.configuration
        if (!bounds || alert.detector_config) {
            return []
        }

        const isRelative = alert.condition.type !== AlertConditionType.ABSOLUTE_VALUE
        const previous = isRelative ? alertPreviousValue(alert, context) : null
        if (isRelative && previous == null) {
            return []
        }

        const scale = funnelThresholdScale(alert, context)
        if (scale == null) {
            return []
        }
        return (['upper', 'lower'] as const).flatMap((bound) => {
            const limit = bounds[bound]
            if (limit == null || !Number.isFinite(limit)) {
                return []
            }
            let value = limit
            if (isRelative && previous != null) {
                const change = type === InsightThresholdType.PERCENTAGE ? previous * limit : limit
                value = previous + (alert.condition.type === AlertConditionType.RELATIVE_INCREASE ? change : -change)
            }
            value *= scale
            if (!Number.isFinite(value)) {
                return []
            }
            return [{ label: `${alert.name} ${bound === 'upper' ? 'Upper' : 'Lower'} Threshold`, value }]
        })
    })
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface insightAlertsLogicValues {
    insight: Partial<InsightModel<Node<Record<string, any>>>> // insightLogic
    breakdownFilter: BreakdownFilter | null | undefined // insightVizDataLogic
    insightData: Record<string, any> // insightVizDataLogic
    querySource:
        | FunnelsQuery
        | LifecycleQuery
        | PathsQuery
        | PathsV2Query
        | RetentionQuery
        | StickinessQuery
        | TrendsQuery
        | WebOverviewQuery
        | WebStatsTableQuery
        | null // insightVizDataLogic
    showAlertThresholdLines: boolean | null | undefined // insightVizDataLogic
    alertAnomalyPoints: AnomalyPoint[]
    alertDestinationCounts: Record<string, number>
    alertDestinationCountsLoading: boolean
    alertThresholdLines: GoalLine[]
    alerts: AlertType[]
    alertsLoading: boolean
    allAlertThresholdLines: GoalLine[]
    hasDetectorAlerts: boolean
    shouldShowAlertDeletionWarning: boolean
    showAlertAnomalyPointsFlag: boolean
    simulationAnomalyPoints: AnomalyPoint[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface insightAlertsLogicActions {
    setQuery: (
        query: Node<Record<string, any>> | null,
        fromUrl?: boolean | undefined
    ) => {
        fromUrl: boolean
        query: Node<Record<string, any>> | null
    } // insightVizDataLogic
    clearSimulationAnomalyPoints: () => {
        value: true
    }
    loadAlertDestinationCounts: (alerts: AlertType[]) => AlertType[]
    loadAlertDestinationCountsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAlertDestinationCountsSuccess: (
        alertDestinationCounts: Record<string, number>,
        payload?: AlertType[]
    ) => {
        alertDestinationCounts: Record<string, number>
        payload?: AlertType[]
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
    setAlertsFromInsight: (alerts: AlertType[]) => {
        alerts: AlertType[]
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
        allAlertThresholdLines: (
            alerts: AlertType[],
            querySource:
                | FunnelsQuery
                | TrendsQuery
                | null
                | import('~/queries/schema').LifecycleQuery
                | import('~/queries/schema').PathsQuery
                | import('~/queries/schema').PathsV2Query
                | import('~/queries/schema').RetentionQuery
                | import('~/queries/schema').StickinessQuery
                | import('~/queries/schema').WebOverviewQuery
                | import('~/queries/schema').WebStatsTableQuery,
            insightData: Record<string, any>
        ) => GoalLine[]
        alertThresholdLines: (
            allAlertThresholdLines: GoalLine[],
            showAlertThresholdLines: boolean | null | undefined
        ) => GoalLine[]
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
        setAlertsFromInsight: (alerts: AlertType[]) => ({ alerts }),
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
            ['showAlertThresholdLines', 'breakdownFilter', 'insightData', 'querySource'],
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
        alertDestinationCounts: [
            {} as Record<string, number>,
            {
                loadAlertDestinationCounts: async (alerts: AlertType[]) => {
                    if (alerts.length === 0) {
                        return {}
                    }
                    const alertIds = new Set(alerts.map((alert) => alert.id))
                    const response = await api.hogFunctions.list({
                        types: ['internal_destination'],
                        filter_groups: alerts.map((alert) => buildAlertFilterConfig(alert.id)),
                        full: true,
                        limit: 500,
                    })
                    return response.results.reduce<Record<string, number>>((counts, hogFunction) => {
                        const alertIdProperty = hogFunction.filters?.properties?.find(
                            (property) => property.key === 'alert_id'
                        )
                        const alertId = alertIdProperty?.value
                        if (typeof alertId === 'string' && alertIds.has(alertId)) {
                            counts[alertId] = (counts[alertId] ?? 0) + 1
                        }
                        return counts
                    }, {})
                },
            },
        ],
    })),

    reducers({
        alerts: [
            [] as AlertType[],
            {
                setAlertsFromInsight: (_, { alerts }) => alerts,
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
        allAlertThresholdLines: [
            (s) => [s.alerts, s.querySource, s.insightData],
            (
                alerts: AlertType[],
                querySource:
                    | FunnelsQuery
                    | TrendsQuery
                    | null
                    | import('~/queries/schema').LifecycleQuery
                    | import('~/queries/schema').PathsQuery
                    | import('~/queries/schema').PathsV2Query
                    | import('~/queries/schema').RetentionQuery
                    | import('~/queries/schema').StickinessQuery
                    | import('~/queries/schema').WebOverviewQuery
                    | import('~/queries/schema').WebStatsTableQuery,
                insightData: Record<string, any>
            ): GoalLine[] =>
                alertsToThresholdGoalLines(
                    alerts,
                    isTrendsQuery(querySource) || isFunnelsQuery(querySource)
                        ? { query: querySource, results: Array.isArray(insightData?.result) ? insightData.result : [] }
                        : undefined
                ),
        ],
        alertThresholdLines: [
            (s) => [s.allAlertThresholdLines, s.showAlertThresholdLines],
            (lines: GoalLine[], show: boolean | null | undefined): GoalLine[] => (show ? lines : []),
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
        loadAlertsSuccess: ({ alerts }) => {
            actions.loadAlertDestinationCounts(alerts)
        },
        upsertAlert: () => {
            actions.loadAlertDestinationCounts(values.alerts)
        },
        setQuery: ({ query }) => {
            actions.setShouldShowAlertDeletionWarning(values.alerts.length > 0 && !alertsSurviveQuery(query))
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
        // If the insight has an alerts property (even if empty), use it - this means the backend sent us the alerts data
        if (values.insight?.alerts && Array.isArray(values.insight.alerts)) {
            if (props.deferInitialAlertsLoad) {
                // Hydrate without loadAlertsSuccess: its listener fetches destination counts per
                // insight, which dashboards must not fan out on mount. Threshold lines only need
                // the alerts themselves; ManageAlertsModal loads the rest when opened.
                actions.setAlertsFromInsight(values.insight.alerts)
            } else {
                actions.loadAlertsSuccess(values.insight.alerts)
            }
            return
        }
        if (props.deferInitialAlertsLoad) {
            return
        }
        // No alerts property means we need to fetch from API (e.g., when viewing insight in isolation)
        actions.loadAlerts()
    }),
])
