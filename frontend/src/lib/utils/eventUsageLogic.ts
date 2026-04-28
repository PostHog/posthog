import { actions, connect, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { Dayjs } from 'lib/dayjs'
import { now } from 'lib/dayjs'
import { TimeToSeeDataPayload } from 'lib/internalMetrics'
import { objectClean } from 'lib/utils'
import { BillingUsageInteractionProps } from 'scenes/billing/types'
import { SharedMetric } from 'scenes/experiments/SharedMetrics/sharedMetricLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { ProductTourEvent } from 'scenes/product-tours/constants'
import { NewSurvey, SURVEY_CREATED_SOURCE, SurveyTemplateType } from 'scenes/surveys/constants'
import { userLogic } from 'scenes/userLogic'

import {
    Breakdown,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentMetricSource,
    ExperimentRetentionMetric,
    ExperimentTrendsQuery,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
    isExperimentRetentionMetric,
    Node,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    getBreakdown,
    getCompareFilter,
    getDisplay,
    getFormula,
    getInterval,
    getSeries,
    isActionsNode,
    isAnyDataWarehouseNode,
    isEventsNode,
    isFunnelsQuery,
    isInsightQueryNode,
    isInsightVizNode,
    isNodeWithSource,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { PROPERTY_KEYS } from '~/taxonomy/taxonomy'
import {
    ChartDisplayType,
    CohortType,
    DashboardMode,
    DashboardTemplateScope,
    DashboardTile,
    DashboardWidgetType,
    DashboardType,
    EntityType,
    Experiment,
    ExperimentHoldoutType,
    ExperimentIdType,
    ExperimentStatsMethod,
    FilterLogicalOperator,
    FunnelCorrelation,
    HelpType,
    InsightShortId,
    MultipleSurveyQuestion,
    OnboardingStepKey,
    PersonType,
    ProductTour,
    PropertyFilterType,
    QueryBasedInsightModel,
    type SDK,
    Survey,
    SurveyQuestionType,
} from '~/types'

import type { eventUsageLogicType } from './eventUsageLogicType'

export enum DashboardEventSource {
    LongPress = 'long_press',
    MoreDropdown = 'more_dropdown',
    DashboardHeaderSaveDashboard = 'dashboard_header_save_dashboard',
    DashboardHeaderDiscardChanges = 'dashboard_header_discard_changes',
    DashboardHeaderExitFullscreen = 'dashboard_header_exit_fullscreen',
    DashboardHeaderOverridesBanner = 'dashboard_header_overrides_banner',
    Hotkey = 'hotkey',
    InputEnter = 'input_enter',
    Toast = 'toast',
    Browser = 'browser',
    AddDescription = 'add_dashboard_description',
    MainNavigation = 'main_nav',
    DashboardsList = 'dashboards_list',
    SceneCommonButtons = 'scene_common_buttons',
    CardEdgeHover = 'card_edge_hover',
    CardDragHandle = 'card_drag_handle',
    DashboardFilters = 'dashboard_filters',
    DashboardInsightColorsModal = 'dashboard_insight_colors_modal',
    DashboardVariableOverride = 'dashboard_variable_override',
}

export enum InsightEventSource {
    LongPress = 'long_press',
    MoreDropdown = 'more_dropdown',
    InsightHeader = 'insight_header',
    Hotkey = 'hotkey',
    InputEnter = 'input_enter',
    Toast = 'toast',
    Browser = 'browser',
    AddDescription = 'add_insight_description',
}

export enum GraphSeriesAddedSource {
    Default = 'default',
    Duplicate = 'duplicate',
}

function retentionWindowDays(metric: ExperimentRetentionMetric): number | undefined {
    const unitToDays: Record<string, number> = { day: 1, week: 7, month: 30 }
    const multiplier = unitToDays[metric.retention_window_unit]
    return multiplier ? (metric.retention_window_end - metric.retention_window_start) * multiplier : undefined
}

function getSourceProperties(source: ExperimentMetricSource): {
    source_kind: string
    is_data_warehouse: boolean
    property_filter_count: number
    math_type: string | undefined
    has_math_hogql: boolean
} {
    return {
        source_kind: source.kind,
        is_data_warehouse: source.kind === NodeKind.ExperimentDataWarehouseNode,
        property_filter_count: (source.properties?.length ?? 0) + (source.fixedProperties?.length ?? 0),
        math_type: source.math,
        has_math_hogql: !!source.math_hogql,
    }
}

export function getEventPropertiesForMetric(
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
): object {
    if (metric.kind === NodeKind.ExperimentMetric) {
        const base = {
            kind: NodeKind.ExperimentMetric,
            metric_type: metric.metric_type,
            has_breakdown: !!metric.breakdownFilter,
        }

        if (isExperimentFunnelMetric(metric)) {
            const totalFilterCount = metric.series.reduce(
                (sum, step) => sum + (step.properties?.length ?? 0) + (step.fixedProperties?.length ?? 0),
                0
            )
            return {
                ...base,
                funnel_steps_count: metric.series.length,
                funnel_order_type: metric.funnel_order_type,
                property_filter_count: totalFilterCount,
            }
        }

        if (isExperimentMeanMetric(metric)) {
            return {
                ...base,
                ...getSourceProperties(metric.source),
            }
        }

        if (isExperimentRatioMetric(metric)) {
            const numeratorProps = getSourceProperties(metric.numerator)
            const denominatorProps = getSourceProperties(metric.denominator)
            return {
                ...base,
                numerator_source_kind: numeratorProps.source_kind,
                denominator_source_kind: denominatorProps.source_kind,
                is_data_warehouse: numeratorProps.is_data_warehouse || denominatorProps.is_data_warehouse,
                property_filter_count: numeratorProps.property_filter_count + denominatorProps.property_filter_count,
                numerator_math_type: numeratorProps.math_type,
                denominator_math_type: denominatorProps.math_type,
                has_math_hogql: numeratorProps.has_math_hogql || denominatorProps.has_math_hogql,
            }
        }

        if (isExperimentRetentionMetric(metric)) {
            const startProps = getSourceProperties(metric.start_event)
            const completionProps = getSourceProperties(metric.completion_event)
            return {
                ...base,
                is_data_warehouse: startProps.is_data_warehouse || completionProps.is_data_warehouse,
                property_filter_count: startProps.property_filter_count + completionProps.property_filter_count,
                retention_window_days: retentionWindowDays(metric),
            }
        }

        return base
    } else if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        return {
            kind: NodeKind.ExperimentFunnelsQuery,
            steps_count: metric.funnels_query?.series?.length,
            filter_test_accounts: metric.funnels_query?.filterTestAccounts,
        }
    }
    return {
        kind: NodeKind.ExperimentTrendsQuery,
        series_kind: metric.count_query?.series?.[0]?.kind,
        filter_test_accounts: metric.count_query?.filterTestAccounts,
    }
}

export function getEventPropertiesForExperiment(experiment: Experiment): object {
    const allMetrics = [
        ...experiment.metrics,
        ...experiment.saved_metrics.filter((m) => m.metadata.type === 'primary').map((m) => m.query),
    ]
    const allSecondaryMetrics = [
        ...experiment.metrics_secondary,
        ...experiment.saved_metrics.filter((m) => m.metadata.type === 'secondary').map((m) => m.query),
    ]

    return {
        id: experiment.id,
        name: experiment.name,
        type: experiment.type,
        parameters: experiment.parameters,
        metrics: allMetrics.map((m) => getEventPropertiesForMetric(m)),
        secondary_metrics: allSecondaryMetrics.map((m) => getEventPropertiesForMetric(m)),
        metrics_count: allMetrics.length,
        secondary_metrics_count: allSecondaryMetrics.length,
        saved_metrics_count: experiment.saved_metrics.length,
        stats_method: experiment.stats_config?.method || ExperimentStatsMethod.Bayesian,
    }
}

function sanitizeInsight(insight: Partial<QueryBasedInsightModel> | null): object | undefined {
    if (!insight) {
        return undefined
    }

    // Remove results
    const { result, ...sanitizedInsight } = insight

    if (sanitizedInsight.query) {
        return {
            ...sanitizedInsight,
            query: sanitizeQuery(sanitizedInsight.query),
        }
    }

    return sanitizedInsight
}

function sanitizeTile(tile: DashboardTile<QueryBasedInsightModel> | null): object | undefined {
    if (!tile) {
        return undefined
    }

    return {
        ...tile,
        insight: tile.insight ? sanitizeInsight(tile.insight) : undefined,
    }
}

function sanitizeDashboard(dashboard: DashboardType<QueryBasedInsightModel> | null): object | null {
    if (!dashboard) {
        return null
    }

    return {
        ...dashboard,
        tiles: dashboard.tiles?.map((tile) => sanitizeTile(tile)) || [],
    }
}

/** Takes a query and returns an object with "useful" properties that don't contain sensitive data. */
function sanitizeQuery(query: Node | null): Record<string, string | number | boolean | undefined> {
    const payload: Record<string, string | number | boolean | undefined> = {
        query_kind: query?.kind,
        query_source_kind: isNodeWithSource(query) ? query.source.kind : undefined,
    }

    if (isInsightVizNode(query) || isInsightQueryNode(query)) {
        const querySource = isInsightVizNode(query) ? query.source : query
        const { dateRange, filterTestAccounts, properties } = querySource
        const samplingFactor = 'samplingFactor' in querySource ? querySource.samplingFactor : undefined

        // date range and sampling
        payload.date_from = dateRange?.date_from || undefined
        payload.date_to = dateRange?.date_to || undefined
        payload.interval = getInterval(querySource)
        payload.samplingFactor = samplingFactor || undefined

        // series
        payload.series_length = getSeries(querySource)?.length
        payload.event_entity_count = getSeries(querySource)?.filter((e) => isEventsNode(e)).length
        payload.action_entity_count = getSeries(querySource)?.filter((e) => isActionsNode(e)).length
        payload.data_warehouse_entity_count = getSeries(querySource)?.filter((e) => isAnyDataWarehouseNode(e)).length

        // properties
        payload.has_properties = !!properties
        payload.filter_test_accounts = filterTestAccounts

        // breakdown
        payload.breakdown_type = getBreakdown(querySource)?.breakdown_type || undefined
        payload.breakdown_limit = getBreakdown(querySource)?.breakdown_limit || undefined
        payload.breakdown_hide_other_aggregation =
            getBreakdown(querySource)?.breakdown_hide_other_aggregation || undefined

        // trends like
        payload.has_formula = !!getFormula(querySource)
        payload.display =
            getDisplay(querySource) ??
            (isTrendsQuery(querySource) || isStickinessQuery(querySource)
                ? ChartDisplayType.ActionsLineGraph
                : undefined)
        payload.compare = getCompareFilter(querySource)?.compare
        payload.compare_to = getCompareFilter(querySource)?.compare_to

        // funnels
        payload.funnel_viz_type = isFunnelsQuery(querySource) ? querySource.funnelsFilter?.funnelVizType : undefined
        payload.funnel_order_type = isFunnelsQuery(querySource) ? querySource.funnelsFilter?.funnelOrderType : undefined
    }

    return objectClean(payload)
}

const reportedMissingTaxonomyEntries = new Set<string>()

export const eventUsageLogic = kea<eventUsageLogicType>([
    path(['lib', 'utils', 'eventUsageLogic']),
    connect(() => ({
        values: [preflightLogic, ['realm'], userLogic, ['user']],
    })),
    actions({
        // persons related
        reportPersonDetailViewed: (person: PersonType) => ({ person }),
        reportPersonsModalViewed: (params: any) => ({
            params,
        }),
        reportPersonsModalSearched: (params: { teamId?: number | null; actorType?: string }) => ({ params }),
        // timing
        reportTimeToSeeData: (payload: TimeToSeeDataPayload) => ({ payload }),
        reportGroupTypeDetailDashboardCreated: () => ({}),
        reportGroupPropertyUpdated: (
            action: 'added' | 'updated' | 'removed',
            totalProperties: number,
            oldPropertyType?: string,
            newPropertyType?: string
        ) => ({ action, totalProperties, oldPropertyType, newPropertyType }),
        // insights
        reportInsightMetadataAiGenerated: (queryKind: NodeKind) => ({ queryKind }),
        reportInsightMetadataAiGenerationFailed: (queryKind: NodeKind) => ({ queryKind }),
        reportInsightCreated: (query: Node | null) => ({ query }),
        reportInsightSaved: (
            insight: Partial<QueryBasedInsightModel> | null,
            query: Node | null,
            isNewInsight: boolean,
            saveType: 'save' | 'save_as'
        ) => ({ insight, query, isNewInsight, saveType }),
        reportInsightViewed: (
            insightModel: Partial<QueryBasedInsightModel>,
            query: Node | null,
            isFirstLoad: boolean,
            delay?: number
        ) => ({
            insightModel,
            query,
            isFirstLoad,
            delay,
        }),
        reportFunnelCalculated: (
            eventCount: number,
            actionCount: number,
            interval: string,
            funnelVizType: string | undefined,
            success: boolean,
            error?: string
        ) => ({
            eventCount,
            actionCount,
            interval,
            funnelVizType,
            success,
            error,
        }),
        reportDataTableColumnsUpdated: (context_type: string) => ({ context_type }),
        // insight filters
        reportFunnelStepReordered: true,
        reportInsightFilterRemoved: (index: number) => ({ index }),
        reportInsightFilterAdded: (newLength: number, source: GraphSeriesAddedSource) => ({ newLength, source }),
        reportInsightFilterSet: (
            filters: Array<{
                id: string | number | null
                type?: EntityType
            }>
        ) => ({ filters }),
        reportInsightWhitelabelToggled: (isWhiteLabelled: boolean) => ({ isWhiteLabelled }),
        reportEntityFilterVisibilitySet: (index: number, visible: boolean, entityName?: string) => ({
            index,
            visible,
            entityName,
        }),
        reportInsightsTableCalcToggled: (mode: string) => ({ mode }),
        reportPropertyGroupFilterAdded: true,
        reportPropertyGroupFilterRemoved: true,
        reportPropertyGroupFilterDuplicated: true,
        reportInsightDateRangeChanged: (queryKind: string | undefined) => ({ queryKind }),
        reportInsightBreakdownChanged: (queryKind: string | undefined) => ({ queryKind }),
        reportInsightCompareChanged: (queryKind: string | undefined) => ({ queryKind }),
        reportChangeOuterPropertyGroupFiltersType: (type: FilterLogicalOperator, groupsLength: number) => ({
            type,
            groupsLength,
        }),
        reportChangeInnerPropertyGroupFiltersType: (type: FilterLogicalOperator, filtersLength: number) => ({
            type,
            filtersLength,
        }),
        // insight funnel correlation
        reportCorrelationViewed: (query: Node | null, delay?: number, propertiesTable?: boolean) => ({
            query,
            delay, // Number of delayed seconds to report event (useful to measure insights where users don't navigate immediately away)
            propertiesTable,
        }),
        reportCorrelationInteraction: (
            correlationType: FunnelCorrelation['result_type'],
            action: string,
            props?: Record<string, any>
        ) => ({ correlationType, action, props }),
        reportProjectCreationSubmitted: (projectCount: number, nameLength: number) => ({ projectCount, nameLength }),
        reportProjectNoticeDismissed: (key: string) => ({ key }),
        reportProjectNoticeShown: (variant: string) => ({ variant }),
        reportPersonPropertyUpdated: (
            action: 'added' | 'updated' | 'removed',
            totalProperties: number,
            oldPropertyType?: string,
            newPropertyType?: string
        ) => ({ action, totalProperties, oldPropertyType, newPropertyType }),
        reportDashboardViewed: (
            dashboard: DashboardType<QueryBasedInsightModel>,
            lastRefreshed: Dayjs | null,
            delay?: number
        ) => ({
            dashboard,
            delay,
            lastRefreshed,
        }),
        reportDashboardModeToggled: (
            dashboard: DashboardType<QueryBasedInsightModel> | null,
            mode: DashboardMode | null,
            source: DashboardEventSource | null,
            layoutZoom: number | null
        ) => ({ dashboard, mode, source, layoutZoom }),
        reportDashboardLayoutZoomChanged: (
            dashboard: DashboardType<QueryBasedInsightModel> | null,
            layoutZoom: number,
            source: 'button' | 'shortcut'
        ) => ({ dashboard, layoutZoom, source }),
        reportDashboardRefreshed: (
            dashboardId: number,
            dashboard: DashboardType<QueryBasedInsightModel> | null,
            filters: Record<string, any>,
            variables: Record<string, any>,
            lastRefreshed: string | Dayjs | null,
            action: string,
            forceRefresh: boolean,
            insightsRefreshedInfo: {
                totalTileCount: number
                tilesStaleCount: number
                tilesRefreshedCount: number
                tilesErroredCount: number
                tilesAbortedCount: number
                refreshDurationMs: number
            }
        ) => ({
            dashboardId,
            dashboard,
            filters,
            variables,
            lastRefreshed,
            action,
            forceRefresh,
            insightsRefreshedInfo,
        }),
        reportDashboardTileRefreshed: (
            dashboardId: number,
            tile: DashboardTile<QueryBasedInsightModel>,
            filters: Record<string, any>,
            variables: Record<string, any>,
            refreshDurationMs: number,
            individualRefresh: boolean
        ) => ({
            dashboardId,
            tile,
            filters,
            variables,
            refreshDurationMs,
            individualRefresh,
        }),
        reportDashboardDateRangeChanged: (
            dashboard: DashboardType<QueryBasedInsightModel> | null,
            dateFrom?: string | Dayjs | null,
            dateTo?: string | Dayjs | null
        ) => ({
            dashboard,
            dateFrom,
            dateTo,
        }),
        reportDashboardPropertiesChanged: (dashboard: DashboardType<QueryBasedInsightModel> | null) => ({ dashboard }),
        reportDashboardPinToggled: (pinned: boolean, source: DashboardEventSource) => ({
            pinned,
            source,
        }),
        reportDashboardFrontEndUpdate: (
            attribute: 'name' | 'description' | 'tags',
            originalLength: number,
            newLength: number
        ) => ({ attribute, originalLength, newLength }),
        reportDashboardShareToggled: (isShared: boolean) => ({ isShared }),
        reportDashboardWhitelabelToggled: (isWhiteLabelled: boolean) => ({ isWhiteLabelled }),
        reportDashboardTileRepositioned: (dashboardId: number, action: 'moved' | 'resized', layoutZoom: number) => ({
            dashboardId,
            action,
            layoutZoom,
        }),
        reportDashboardInsightMetaUpdated: (
            dashboardId: number | undefined,
            insightId: number,
            attribute: 'name' | 'description'
        ) => ({ dashboardId, insightId, attribute }),
        reportDashboardInsightValuesOnSeriesToggled: (
            dashboardId: number | undefined,
            insightId: number,
            source: DashboardEventSource
        ) => ({ dashboardId, insightId, source }),
        reportDashboardInsightLegendToggled: (
            dashboardId: number | undefined,
            insightId: number,
            source: DashboardEventSource
        ) => ({ dashboardId, insightId, source }),
        /** Empty-state AI prompt chips (ai-first empty dashboard only). */
        reportDashboardEmptyAiPromptClicked: (promptLabel: string, dashboardId: number | undefined) => ({
            promptLabel,
            dashboardId,
        }),
        reportUpgradeModalShown: (featureName: string) => ({ featureName }),
        reportTimezoneComponentViewed: (
            component: 'label' | 'indicator',
            project_timezone?: string,
            device_timezone?: string | null
        ) => ({ component, project_timezone, device_timezone }),
        reportTestAccountFiltersUpdated: (filters: Record<string, any>[]) => ({ filters }),
        reportPoEModeUpdated: (mode: string) => ({ mode }),
        reportPersonsJoinModeUpdated: (mode: string) => ({ mode }),
        reportBounceRatePageViewModeUpdated: (mode: string) => ({ mode }),
        reportSessionTableVersionUpdated: (version: string) => ({ version }),
        reportCustomChannelTypeRulesUpdated: (numRules: number) => ({ numRules }),
        reportPropertySelectOpened: true,
        reportCreatedDashboardFromModal: true,
        /** Dashboard created via PostHog web app from a template (new dashboard modal / template chooser). */
        reportWebDashboardCreatedFromTemplate: (payload: {
            dashboard_id: number
            template_id: string
            template_name: string
            template_variable_count: number
            template_scope: DashboardTemplateScope | null
        }) => payload,
        reportSavedInsightToDashboard: (
            insight: Partial<QueryBasedInsightModel> | null,
            dashboardId: number | null
        ) => ({ insight, dashboardId }),
        reportRemovedInsightFromDashboard: (
            insight: Partial<QueryBasedInsightModel> | null,
            dashboardId: number | null
        ) => ({ insight, dashboardId }),
        reportCopiedDashboardTileToDashboard: (
            fromDashboardId: number,
            toDashboardId: number,
            tileType: DashboardWidgetType
        ) => ({ fromDashboardId, toDashboardId, tileType }),
        reportSavedInsightTabChanged: (tab: string) => ({ tab }),
        reportSavedInsightFilterUsed: (filterKeys: string[]) => ({ filterKeys }),
        reportSavedInsightNewInsightClicked: (insightType: string) => ({ insightType }),
        reportPersonSplit: (merge_count: number) => ({ merge_count }),
        reportHelpButtonViewed: true,
        reportHelpButtonUsed: (help_type: HelpType) => ({ help_type }),
        reportExperimentWizardStarted: (guideVisible: boolean) => ({ guideVisible }),
        reportExperimentWizardGuideToggled: (visible: boolean, currentStep: string) => ({ visible, currentStep }),
        reportExperimentCreated: (
            experiment: Experiment,
            metadata?: { creation_source?: string; has_linked_flag?: boolean }
        ) => ({ experiment, metadata }),
        reportExperimentUpdated: (experiment: Experiment) => ({ experiment }),
        reportExperimentViewed: (experiment: Experiment, duration: number | null) => ({ experiment, duration }),
        reportExperimentInconsistencyWarningShown: (experiment: Experiment, warningKey: string) => ({
            experiment,
            warningKey,
        }),
        reportExperimentMetricsRefreshed: (
            experiment: Experiment,
            forceRefresh: boolean,
            context?: {
                triggered_by: 'manual' | 'auto-refresh'
                auto_refresh_enabled?: boolean
                auto_refresh_interval?: number
            }
        ) => ({
            experiment,
            forceRefresh,
            context,
        }),
        reportExperimentAutoRefreshToggled: (experiment: Experiment, enabled: boolean, interval: number) => ({
            experiment,
            enabled,
            interval,
        }),
        reportExperimentMetricBreakdownAdded: (
            experiment: Experiment,
            metricUuid: string,
            breakdown: Breakdown,
            isPrimary: boolean
        ) => ({
            experiment,
            metricUuid,
            breakdown,
            isPrimary,
        }),
        reportExperimentMetricBreakdownRemoved: (
            experiment: Experiment,
            metricUuid: string,
            breakdown: Breakdown,
            index: number,
            isPrimary: boolean
        ) => ({
            experiment,
            metricUuid,
            breakdown,
            index,
            isPrimary,
        }),
        reportExperimentStartDateChange: (experiment: Experiment, newStartDate: string) => ({
            experiment,
            newStartDate,
        }),
        reportExperimentEndDateChange: (experiment: Experiment, newEndDate: string) => ({
            experiment,
            newEndDate,
        }),
        reportExperimentExposureCohortCreated: (experiment: Experiment, cohort: CohortType) => ({ experiment, cohort }),
        reportExperimentExposureCohortEdited: (existingCohort: CohortType, newCohort: CohortType) => ({
            existingCohort,
            newCohort,
        }),
        reportExperimentInsightLoadFailed: true,
        reportExperimentVariantScreenshotUploaded: (experimentId: ExperimentIdType) => ({ experimentId }),
        reportExperimentResultsLoadingTimeout: (experimentId: ExperimentIdType) => ({ experimentId }),
        reportExperimentReleaseConditionsViewed: (experimentId: ExperimentIdType) => ({ experimentId }),
        reportExperimentReleaseConditionsUpdated: (experimentId: ExperimentIdType) => ({ experimentId }),
        reportExperimentHoldoutCreated: (holdout: ExperimentHoldoutType) => ({ holdout }),
        reportExperimentHoldoutAssigned: ({
            experimentId,
            holdoutId,
        }: {
            experimentId: ExperimentIdType
            holdoutId: ExperimentHoldoutType['id']
        }) => ({ experimentId, holdoutId }),
        reportExperimentSharedMetricCreated: (sharedMetric: SharedMetric) => ({ sharedMetric }),
        reportExperimentSharedMetricAssigned: (experimentId: ExperimentIdType, sharedMetric: SharedMetric) => ({
            experimentId,
            sharedMetric,
        }),
        reportExperimentDashboardCreated: (experiment: Experiment, dashboardId: number) => ({
            experiment,
            dashboardId,
        }),
        reportExperimentMetricFinished: (
            experimentId: ExperimentIdType,
            metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery,
            teamId?: number | null,
            queryId?: string | null,
            context?: {
                duration_ms: number
                is_cached: boolean
                metric_index: number
                is_primary: boolean
                is_retry: boolean
                refresh_id: string
                metric_kind: string
                execution_mode: 'sync' | 'async'
            }
        ) => ({
            experimentId,
            metric,
            teamId,
            queryId,
            context,
        }),
        reportExperimentMetricError: (
            experimentId: ExperimentIdType,
            metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery,
            teamId: number | null | undefined,
            queryId: string | null,
            context: {
                duration_ms: number
                metric_index: number
                is_primary: boolean
                is_retry: boolean
                refresh_id: string
                metric_kind: string
                error_type:
                    | 'timeout'
                    | 'out_of_memory'
                    | 'server_error'
                    | 'network_error'
                    | 'not_found'
                    | 'authentication'
                    | 'authorization'
                    | 'validation_error'
                    | 'unknown'
                error_code: string | null
                error_message: string | null
                error_detail: string | null
                status_code: number | null
            }
        ) => ({
            experimentId,
            metric,
            teamId,
            queryId,
            context,
        }),
        reportExperimentResultsRefreshCompleted: (
            experimentId: ExperimentIdType,
            teamId: number | null | undefined,
            context: {
                total_duration_ms: number
                primary_metrics_count: number
                secondary_metrics_count: number
                successful_count: number
                errored_count: number
                cached_count: number
                triggered_by: 'page_load' | 'manual' | 'auto_refresh' | 'config_change'
                force_refresh: boolean
                refresh_id: string
                experiment_duration_hours: number | null
                experiment_status: string | null
                total_metrics_count: number
                execution_mode: 'sync' | 'async'
            }
        ) => ({
            experimentId,
            teamId,
            context,
        }),
        reportExperimentFeatureFlagModalOpened: () => ({}),
        reportExperimentFeatureFlagSelected: (featureFlagKey: string) => ({ featureFlagKey }),
        reportExperimentTimeseriesViewed: (experimentId: ExperimentIdType, metric: ExperimentMetric) => ({
            experimentId,
            metric,
        }),
        reportExperimentTimeseriesRecalculated: (experimentId: ExperimentIdType, metric: ExperimentMetric) => ({
            experimentId,
            metric,
        }),
        reportExperimentAiSummaryRequested: (experiment: Experiment) => ({ experiment }),
        reportExperimentSessionReplaySummaryRequested: (experiment: Experiment) => ({ experiment }),
        // Taxonomic Filter
        reportTaxonomicFilterCategorySelected: (groupType: TaxonomicFilterGroupType, eventName?: string) => ({
            groupType,
            eventName,
        }),
        reportTaxonomicFilterAddFilterClicked: (eventName?: string) => ({ eventName }),
        reportMissingTaxonomyEntries: (entries: { name: string; groupType: TaxonomicFilterGroupType }[]) => ({
            entries,
        }),
        // Definition Popover
        reportDataManagementDefinitionHovered: (type: TaxonomicFilterGroupType, mediaPreviewCount?: number) => ({
            type,
            mediaPreviewCount,
        }),
        reportMediaPreviewUploaded: (source: string) => ({ source }),
        reportDataManagementDefinitionClickView: (type: TaxonomicFilterGroupType) => ({ type }),
        reportDataManagementDefinitionClickEdit: (type: TaxonomicFilterGroupType) => ({ type }),
        // Group view Shortcuts
        reportGroupViewSaved: (groupTypeIndex: number, shortcutName: string) => ({
            groupTypeIndex,
            shortcutName,
        }),
        reportDataManagementDefinitionSaveSucceeded: (type: TaxonomicFilterGroupType, loadTime: number) => ({
            type,
            loadTime,
        }),
        reportDataManagementDefinitionSaveFailed: (
            type: TaxonomicFilterGroupType,
            loadTime: number,
            error: string
        ) => ({ type, loadTime, error }),
        reportDataManagementDefinitionCancel: (type: TaxonomicFilterGroupType) => ({ type }),
        // Data Management Pages
        reportDataManagementEventDefinitionsPageLoadSucceeded: (loadTime: number, resultsLength: number) => ({
            loadTime,
            resultsLength,
        }),
        reportDataManagementEventDefinitionsPageLoadFailed: (loadTime: number, error: string) => ({
            loadTime,
            error,
        }),
        reportDataManagementEventDefinitionsPageNestedPropertiesLoadSucceeded: (loadTime: number) => ({
            loadTime,
        }),
        reportDataManagementEventDefinitionsPageNestedPropertiesLoadFailed: (loadTime: number, error: string) => ({
            loadTime,
            error,
        }),
        reportDataManagementEventPropertyDefinitionsPageLoadSucceeded: (loadTime: number, resultsLength: number) => ({
            loadTime,
            resultsLength,
        }),
        reportDataManagementEventPropertyDefinitionsPageLoadFailed: (loadTime: number, error: string) => ({
            loadTime,
            error,
        }),
        reportInsightRefreshTime: (loadingMilliseconds: number, insightShortId: InsightShortId) => ({
            loadingMilliseconds,
            insightShortId,
        }),
        reportInsightOpenedFromRecentInsightList: true,
        reportPersonOpenedFromNewlySeenPersonsList: true,
        reportIngestionContinueWithoutVerifying: true,
        reportAutocaptureToggled: (autocapture_opt_out: boolean) => ({ autocapture_opt_out }),
        reportAutocaptureExceptionsToggled: (autocapture_opt_in: boolean) => ({ autocapture_opt_in }),
        reportHeatmapsToggled: (heatmaps_opt_in: boolean) => ({ heatmaps_opt_in }),
        reportActivityLogSettingToggled: (receive_org_level_activity_logs: boolean | null) => ({
            receive_org_level_activity_logs,
        }),
        reportFailedToCreateFeatureFlagWithCohort: (code: string, detail: string) => ({ code, detail }),
        reportFeatureFlagCopySuccess: true,
        reportFeatureFlagCopyFailure: (error) => ({ error }),
        reportFeatureFlagScheduleSuccess: true,
        reportFeatureFlagScheduleFailure: (error) => ({ error }),
        reportInviteMembersButtonClicked: true,
        reportDashboardLoadingTime: (loadingMilliseconds: number, dashboardId: number) => ({
            loadingMilliseconds,
            dashboardId,
        }),
        reportInstanceSettingChange: (name: string, value: string | boolean | number) => ({ name, value }),
        reportAxisUnitsChanged: (properties: Record<string, any>) => ({ ...properties }),
        reportTeamSettingChange: (name: string, value: any) => ({ name, value }),
        reportProjectSettingChange: (name: string, value: any) => ({ name, value }),
        reportActivationSideBarTaskClicked: (key: string) => ({ key }),
        reportBillingUpgradeClicked: (plan: string) => ({ plan }),
        reportBillingDowngradeClicked: (plan: string) => ({ plan }),
        reportBillingAddonPlanSwitchStarted: (
            fromProduct: string,
            toProduct: string,
            reason: 'upgrade' | 'downgrade'
        ) => ({
            fromProduct,
            toProduct,
            reason,
        }),
        reportRoleCreated: (role: string) => ({ role }),
        reportFlagsCodeExampleInteraction: (optionType: string) => ({
            optionType,
        }),
        reportFlagsCodeExampleLanguage: (language: string) => ({
            language,
        }),
        reportSurveyViewed: (survey: Survey) => ({
            survey,
        }),
        reportSurveyCreated: (
            survey: Survey,
            isDuplicate?: boolean,
            creationSource?: 'wizard' | 'full_editor' | 'quick_create' | 'template' | 'llm_analytics' | 'form_builder'
        ) => ({ survey, isDuplicate, creationSource }),
        reportUserFeedbackButtonClicked: (source: SURVEY_CREATED_SOURCE, meta: Record<string, any>) => ({
            source,
            meta,
        }),
        reportSurveyEdited: (survey: Survey) => ({ survey }),
        reportSurveyArchived: (survey: Survey) => ({ survey }),
        reportSurveyTemplateClicked: (template: SurveyTemplateType, source?: string) => ({ template, source }),
        reportSurveyCycleDetected: (survey: Survey | NewSurvey) => ({ survey }),
        reportSurveyConsolidatedResultsQuery: (
            survey: Survey,
            totalDurationMs: number,
            queryDurations: { aggregate: number; openEnded: number }
        ) => ({ survey, totalDurationMs, queryDurations }),
        reportSurveyEmptyStateViewed: true,
        reportSurveyAiPromptSubmitted: (source: string) => ({ source }),
        reportProductTourViewed: (tour: ProductTour) => ({ tour }),
        reportProductTourCreated: (tour: ProductTour, creationSource?: 'app' | 'toolbar') => ({
            tour,
            creationSource,
        }),
        reportProductTourListViewed: true,
        reportProductUnsubscribed: (product: string) => ({ product }),
        reportSubscribedDuringOnboarding: (productKey: string) => ({ productKey }),
        reportOnboardingStarted: (entrypoint: string) => ({ entrypoint }),
        reportOnboardingStepCompleted: (stepKey: OnboardingStepKey) => ({ stepKey }),
        reportOnboardingStepSkipped: (stepKey: OnboardingStepKey) => ({ stepKey }),
        reportOnboardingCompleted: (productKey: string) => ({ productKey }),
        reportOnboardingUseCaseSelected: (useCase: string, recommendedProducts: readonly string[]) => ({
            useCase,
            recommendedProducts,
        }),
        reportOnboardingUseCaseSkipped: true,
        reportAIChatOnboardingStarted: (variant: string) => ({ variant }),
        reportAIChatOnboardingMessageSent: (stepKey: OnboardingStepKey, messageType: 'chat' | 'button') => ({
            stepKey,
            messageType,
        }),
        reportAIChatOnboardingStepTime: (stepKey: OnboardingStepKey, timeSeconds: number) => ({
            stepKey,
            timeSeconds,
        }),
        reportOnboardingProductSelectionPath: (
            path: 'ai' | 'use_case' | 'browsing_history' | 'manual',
            properties?: {
                useCase?: string
                recommendedProducts?: string[]
                hasBrowsingHistory?: boolean
            }
        ) => ({ path, properties }),
        reportOnboardingProductToggled: (productKey: string, selected: boolean, recommendationSource: string) => ({
            productKey,
            selected,
            recommendationSource,
        }),
        reportBillingCTAShown: true,
        reportBillingUsageInteraction: (properties: BillingUsageInteractionProps) => ({ properties }),
        reportBillingSpendInteraction: (properties: BillingUsageInteractionProps) => ({ properties }),
        reportSDKSelected: (sdk: SDK) => ({ sdk }),
        reportAccountOwnerClicked: ({ name, email }: { name: string; email: string }) => ({ name, email }),
        // revenue analytics
        reportRevenueAnalyticsViewed: (delay?: number) => ({ delay }),
        reportRevenueAnalyticsSettingsViewed: () => ({}),
        reportRevenueAnalyticsOnboardingViewed: () => ({}),
        reportRevenueAnalyticsOnboardingCompleted: (hasEvents: boolean, hasSources: boolean) => ({
            hasEvents,
            hasSources,
        }),
        reportRevenueAnalyticsEventCreated: (eventName: string) => ({ eventName }),
        reportRevenueAnalyticsEventDeleted: (eventName: string) => ({ eventName }),
        reportRevenueAnalyticsEventEdited: (eventName: string) => ({ eventName }),
        reportRevenueAnalyticsDataSourceConnected: (sourceType: string) => ({ sourceType }),
        reportRevenueAnalyticsDataSourceEnabled: (sourceType: string) => ({ sourceType }),
        reportRevenueAnalyticsDataSourceDisabled: (sourceType: string) => ({ sourceType }),
        reportRevenueAnalyticsFilterApplied: (filterCount: number) => ({ filterCount }),
        reportRevenueAnalyticsBreakdownAdded: (breakdownProperty: string, breakdownType: string) => ({
            breakdownProperty,
            breakdownType,
        }),
        reportRevenueAnalyticsBreakdownRemoved: (breakdownProperty: string, breakdownType: string) => ({
            breakdownProperty,
            breakdownType,
        }),
        reportRevenueAnalyticsDateRangeChanged: (dateFrom: string | null, dateTo: string | null) => ({
            dateFrom,
            dateTo,
        }),
        reportRevenueAnalyticsMRRModeChanged: (mrrMode: string) => ({ mrrMode }),
        reportRevenueAnalyticsMRRBreakdownModalOpened: () => ({}),
        reportRevenueAnalyticsGoalConfigured: () => ({}),
        reportRevenueAnalyticsTestAccountFilterUpdated: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        // marketing analytics
        reportMarketingAnalyticsOnboardingViewed: () => ({}),
        reportMarketingAnalyticsOnboardingCompleted: (hasSources: boolean) => ({
            hasSources,
        }),
        reportMarketingAnalyticsDataSourceConnected: (sourceType: string) => ({ sourceType }),
        reportWebAnalyticsHealthStatus: (props: {
            has_pageviews: boolean
            has_pageleaves: boolean
            has_scroll_depth: boolean
            has_web_vitals: boolean
            has_authorized_urls: boolean
            has_reverse_proxy: boolean
            overall_status: string
        }) => ({ props }),
        reportWebAnalyticsHealthTabViewed: (props: {
            overall_status: string
            passed_count: number
            warning_count: number
            error_count: number
        }) => ({ props }),
        reportWebAnalyticsHealthSectionToggled: (props: { category: string; is_expanded: boolean }) => ({ props }),
        reportWebAnalyticsHealthActionClicked: (props: {
            check_id: string
            category: string
            status: string
            is_urgent: boolean
        }) => ({ props }),
        reportWebAnalyticsHealthRefreshed: (props: { overall_status: string; passed_count: number }) => ({ props }),
        reportWebAnalyticsFilterApplied: (props: {
            filter_type: string
            property_filter_category?: PropertyFilterType
            total_filter_count: number
        }) => ({ props }),
        reportWebAnalyticsFilterRemoved: (props: {
            filter_type: string
            property_filter_category?: PropertyFilterType
            total_filter_count: number
        }) => ({ props }),
        reportWebAnalyticsDateRangeChanged: (props: {
            date_from: string | null
            date_to: string | null
            interval: string
        }) => ({ props }),
        reportWebAnalyticsCompareToggled: (props: { enabled: boolean }) => ({ props }),
        reportWebAnalyticsConversionGoalSet: (props: { goal_type: string | null }) => ({ props }),
        reportWebAnalyticsPathCleaningToggled: (props: { enabled: boolean }) => ({ props }),
        // Customer Analytics
        reportCustomerAnalyticsDashboardBusinessModeChanged: ({ business_mode }) => ({ business_mode }),
        reportCustomerAnalyticsDashboardConfigurationButtonClicked: () => true,
        reportCustomerAnalyticsDashboardConfigurationViewed: () => true,
        reportCustomerAnalyticsDashboardConfigureEventWithAIClicked: ({ event }) => ({ event }),
        reportCustomerAnalyticsDashboardDateFilterApplied: ({ filter }) => ({ filter }),
        reportCustomerAnalyticsDashboardEventPickerClicked: ({ event }) => ({ event }),
        reportCustomerAnalyticsAddJoinButtonClicked: ({ table }) => ({ table }),
        reportCustomerAnalyticsDashboardEventsSaved: () => true,
        reportCustomerAnalyticsViewed: (delay?: number) => ({ delay }),
        // Customer Journeys
        reportCustomerJourneyViewed: (journeyId: string, journeyName: string, stepCount: number, delay?: number) => ({
            journeyId,
            journeyName,
            stepCount,
            delay,
        }),
        reportCustomerJourneyCreated: (journeyName: string, stepCount: number, creationSource: string | null) => ({
            journeyName,
            stepCount,
            creationSource,
        }),
        reportCustomerJourneyUpdated: (journeyId: string, journeyName: string, stepCount: number) => ({
            journeyId,
            journeyName,
            stepCount,
        }),
        reportCustomerJourneyDeleted: (journeyId: string) => ({ journeyId }),
        reportCustomerJourneyTemplateSelected: (templateKey: string) => ({ templateKey }),
        reportCustomerJourneyExistingFunnelSelected: (insightId: number) => ({ insightId }),
        reportCustomerJourneyPathExpanded: (pathType: string, dropOff: boolean, stepIndex: number) => ({
            pathType,
            dropOff,
            stepIndex,
        }),
        reportCustomerJourneyStepAddedFromPath: (eventName: string, pathType: string, stepIndex: number) => ({
            eventName,
            pathType,
            stepIndex,
        }),
        reportCustomerJourneyStepsSavedFromEditor: (stepsAdded: number, journeyId: string | null) => ({
            stepsAdded,
            journeyId,
        }),
        reportCustomerJourneyBuilderStepAdded: (stepIndex: number, stepCount: number) => ({ stepIndex, stepCount }),
        reportCustomerJourneyBuilderStepRemoved: (stepIndex: number, stepCount: number) => ({ stepIndex, stepCount }),
        reportGroupProfileViewed: (delay?: number) => ({ delay }),
        reportPersonProfileViewed: (delay?: number) => ({ delay }),
        reportUsageMetricsSettingsViewed: () => true,
        reportUsageMetricsCreateButtonClicked: () => true,
        reportUsageMetricsUpdateButtonClicked: () => true,
        reportUsageMetricCreated: () => true,
        reportUsageMetricUpdated: () => true,
        reportUsageMetricDeleted: () => true,
        // navbar starred
        reportNavbarStarredItemAdded: (itemType: string, itemName: string, isAIFirst: boolean) => ({
            itemType,
            itemName,
            isAIFirst,
        }),
        reportNavbarStarredItemRemoved: (itemType: string, itemName: string, isAIFirst: boolean) => ({
            itemType,
            itemName,
            isAIFirst,
        }),
        reportNavbarStarredItemClicked: (itemType: string, itemName: string, isAIFirst: boolean) => ({
            itemType,
            itemName,
            isAIFirst,
        }),
    }),
    listeners(({ values }) => ({
        reportBillingCTAShown: () => {
            posthog.capture('billing CTA shown')
        },
        reportBillingUsageInteraction: ({ properties }) => {
            posthog.capture('billing usage interaction', properties)
        },
        reportBillingSpendInteraction: ({ properties }) => {
            posthog.capture('billing spend interaction', properties)
        },
        reportAxisUnitsChanged: (properties) => {
            posthog.capture('axis units changed', properties)
        },
        reportInstanceSettingChange: ({ name, value }) => {
            posthog.capture('instance setting change', { name, value })
        },
        reportDashboardLoadingTime: async ({ loadingMilliseconds, dashboardId }) => {
            posthog.capture('dashboard loading time', { loadingMilliseconds, dashboardId })
        },
        reportInsightRefreshTime: async ({ loadingMilliseconds, insightShortId }) => {
            posthog.capture('insight refresh time', { loadingMilliseconds, insightShortId })
        },
        reportPersonDetailViewed: async (
            {
                person,
            }: {
                person: PersonType
            },
            breakpoint
        ) => {
            await breakpoint(500)

            let custom_properties_count = 0
            let posthog_properties_count = 0
            for (const prop of Object.keys(person.properties)) {
                if (PROPERTY_KEYS.includes(prop)) {
                    posthog_properties_count += 1
                } else {
                    custom_properties_count += 1
                }
            }

            const properties = {
                properties_count: Object.keys(person.properties).length,
                has_email: !!person.properties.email,
                has_name: !!person.properties.name,
                custom_properties_count,
                posthog_properties_count,
            }
            posthog.capture('person viewed', properties)
        },
        reportTimeToSeeData: async ({ payload }) => {
            posthog.capture('time to see data', payload)
        },
        reportGroupTypeDetailDashboardCreated: async () => {
            posthog.capture('group type detail dashboard created')
        },
        reportGroupPropertyUpdated: async ({ action, totalProperties, oldPropertyType, newPropertyType }) => {
            posthog.capture(`group property ${action}`, {
                old_property_type: oldPropertyType !== 'undefined' ? oldPropertyType : undefined,
                new_property_type: newPropertyType !== 'undefined' ? newPropertyType : undefined,
                total_properties: totalProperties,
            })
        },
        reportInsightCreated: async ({ query }, breakpoint) => {
            // "insight created" essentially means that the user clicked "New insight"
            await breakpoint(500) // Debounce to avoid multiple quick "New insight" clicks being reported

            posthog.capture('insight created', { ...sanitizeQuery(query), source: 'web' })
        },
        reportInsightMetadataAiGenerated: async ({ queryKind }) => {
            posthog.capture('insight metadata ai generated', { query_kind: queryKind })
        },
        reportInsightMetadataAiGenerationFailed: async ({ queryKind }) => {
            posthog.capture('insight metadata ai generation failed', { query_kind: queryKind })
        },
        reportInsightSaved: async ({ insight, query, isNewInsight, saveType }) => {
            // "insight saved" is a proxy for the new insight's results being valuable to the user
            posthog.capture('insight saved', {
                ...sanitizeQuery(query),
                insight: sanitizeInsight(insight),
                is_new_insight: isNewInsight,
                save_type: saveType,
            })
        },
        reportInsightViewed: ({ insightModel, query, isFirstLoad, delay }) => {
            const payload: Record<string, any> = {
                report_delay: delay,
                is_first_component_load: isFirstLoad,
                viewer_is_creator:
                    insightModel.created_by?.uuid && values.user?.uuid
                        ? insightModel.created_by?.uuid === values.user?.uuid
                        : undefined,
                is_saved: insightModel.saved,
                description_length: insightModel.description?.length ?? 0,
                tags_count: insightModel.tags?.length ?? 0,
                insight: sanitizeInsight(insightModel),
                insight_id: insightModel.id,
                insight_short_id: insightModel.short_id,
                ...sanitizeQuery(query),
            }

            const eventName = delay ? 'insight analyzed' : 'insight viewed'
            posthog.capture(eventName, objectClean({ ...payload, source: 'web' }))
        },
        reportPersonsModalViewed: async ({ params }) => {
            posthog.capture('insight person modal viewed', params)
        },
        reportPersonsModalSearched: async ({ params }) => {
            posthog.capture('insight person modal searched', params)
        },
        reportDashboardViewed: async ({ dashboard, lastRefreshed, delay }, breakpoint) => {
            if (!delay) {
                await breakpoint(500) // Debounce to avoid noisy events from continuous navigation
            }
            const { created_at, is_shared, pinned, creation_mode, id } = dashboard
            const properties: Record<string, any> = {
                created_at,
                is_shared,
                pinned,
                creation_mode,
                viewer_is_creator:
                    dashboard.created_by?.uuid && values.user?.uuid
                        ? dashboard.created_by?.uuid === values.user?.uuid
                        : undefined,
                sample_items_count: 0,
                item_count: dashboard.tiles?.length || 0,
                created_by_system: !dashboard.created_by,
                dashboard_id: id,
                lastRefreshed: lastRefreshed?.toISOString(),
                refreshAge: lastRefreshed ? now().diff(lastRefreshed, 'seconds') : undefined,
                dashboard: sanitizeDashboard(dashboard),
            }

            for (const item of dashboard.tiles || []) {
                if (item.insight) {
                    const query = isNodeWithSource(item.insight.query) ? item.insight.query.source : item.insight.query
                    const key = `${query?.kind || !!item.text ? 'text' : 'empty'}_count`
                    if (!properties[key]) {
                        properties[key] = 1
                    } else {
                        properties[key] += 1
                    }
                    properties.sample_items_count += item.insight.is_sample ? 1 : 0
                } else {
                    if (!properties['text_tiles_count']) {
                        properties['text_tiles_count'] = 1
                    } else {
                        properties['text_tiles_count'] += 1
                    }
                }
            }

            const eventName = delay ? 'dashboard analyzed' : 'viewed dashboard' // `viewed dashboard` name is kept for backwards compatibility
            posthog.capture(eventName, { ...properties, source: 'web' })
        },
        reportProjectCreationSubmitted: async ({
            projectCount,
            nameLength,
        }: {
            projectCount?: number
            nameLength: number
        }) => {
            posthog.capture('project create submitted', {
                current_project_count: projectCount,
                name_length: nameLength,
            })
        },
        reportProjectNoticeDismissed: async ({ key }) => {
            // ProjectNotice was previously called DemoWarning
            posthog.capture('demo warning dismissed', { warning_key: key })
        },
        reportProjectNoticeShown: async ({ variant }) => {
            posthog.capture('project notice shown', { variant })
        },
        reportFunnelCalculated: async ({ eventCount, actionCount, interval, funnelVizType, success, error }) => {
            posthog.capture('funnel result calculated', {
                event_count: eventCount,
                action_count: actionCount,
                total_count_actions_events: eventCount + actionCount,
                interval: interval,
                funnel_viz_type: funnelVizType,
                success: success,
                error: error,
            })
        },
        reportFunnelStepReordered: async () => {
            posthog.capture('funnel step reordered')
        },
        reportDataTableColumnsUpdated: async ({ context_type }) => {
            posthog.capture('data table columns updated', { context_type })
        },
        reportPersonPropertyUpdated: async ({ action, totalProperties, oldPropertyType, newPropertyType }) => {
            posthog.capture(`person property ${action}`, {
                old_property_type: oldPropertyType !== 'undefined' ? oldPropertyType : undefined,
                new_property_type: newPropertyType !== 'undefined' ? newPropertyType : undefined,
                total_properties: totalProperties,
            })
        },
        reportDashboardModeToggled: async ({ dashboard, mode, source, layoutZoom }) => {
            posthog.capture('dashboard mode toggled', {
                dashboard_id: dashboard?.id,
                dashboard: sanitizeDashboard(dashboard),
                mode,
                source,
                layout_zoom: layoutZoom ?? undefined,
            })
        },
        reportDashboardLayoutZoomChanged: async ({ dashboard, layoutZoom, source }) => {
            posthog.capture('dashboard layout zoom changed', {
                dashboard_id: dashboard?.id,
                dashboard: sanitizeDashboard(dashboard),
                layout_zoom: layoutZoom,
                source,
            })
        },
        reportDashboardRefreshed: async ({
            dashboardId,
            dashboard,
            filters,
            variables,
            lastRefreshed,
            action,
            forceRefresh,
            insightsRefreshedInfo,
        }) => {
            posthog.capture(`dashboard refreshed`, {
                dashboard_id: dashboardId,
                dashboard: sanitizeDashboard(dashboard),
                filters,
                variables,
                last_refreshed: lastRefreshed?.toString(),
                refreshAge: lastRefreshed ? now().diff(lastRefreshed, 'seconds') : undefined,
                action: action,
                force_refresh: forceRefresh,
                refresh_duration_ms: insightsRefreshedInfo.refreshDurationMs,
                total_tile_count: insightsRefreshedInfo.totalTileCount,
                tiles_stale_count: insightsRefreshedInfo.tilesStaleCount,
                tiles_refreshed_count: insightsRefreshedInfo.tilesRefreshedCount,
                tiles_errored_count: insightsRefreshedInfo.tilesErroredCount,
                tiles_aborted_count: insightsRefreshedInfo.tilesAbortedCount,
            })
        },
        reportDashboardTileRefreshed: async ({
            dashboardId,
            tile,
            filters,
            variables,
            refreshDurationMs,
            individualRefresh,
        }) => {
            const insight = tile.insight
            const sanitizedQuery = insight?.query ? sanitizeQuery(insight.query) : {}

            posthog.capture('dashboard insight refreshed', {
                dashboard_id: dashboardId,
                insight_id: insight?.id,
                insight_short_id: insight?.short_id,
                was_cached: tile.is_cached,
                last_refreshed: insight?.last_refresh?.toString(),
                refresh_age: insight?.last_refresh ? now().diff(insight?.last_refresh, 'seconds') : undefined,
                filters,
                variables,
                tile: sanitizeTile(tile),
                refresh_duration_ms: refreshDurationMs,
                individual_refresh: individualRefresh,
                ...sanitizedQuery,
            })
        },
        reportDashboardDateRangeChanged: async ({ dashboard, dateFrom, dateTo }) => {
            posthog.capture(`dashboard date range changed`, {
                dashboard_id: dashboard?.id,
                dashboard: sanitizeDashboard(dashboard),
                date_from: dateFrom?.toString() || 'Custom',
                date_to: dateTo?.toString(),
            })
        },
        reportDashboardPropertiesChanged: async ({ dashboard }) => {
            posthog.capture(`dashboard properties changed`, {
                dashboard_id: dashboard?.id,
                dashboard: sanitizeDashboard(dashboard),
            })
        },
        reportDashboardPinToggled: async (payload) => {
            posthog.capture(`dashboard pin toggled`, payload)
        },
        reportDashboardFrontEndUpdate: async ({ attribute, originalLength, newLength }) => {
            posthog.capture(`dashboard frontend updated`, {
                attribute,
                original_length: originalLength,
                new_length: newLength,
            })
        },
        reportDashboardShareToggled: async ({ isShared }) => {
            posthog.capture(`dashboard share toggled`, { is_shared: isShared })
        },
        reportDashboardWhitelabelToggled: async ({ isWhiteLabelled }) => {
            posthog.capture(`dashboard whitelabel toggled`, { is_whitelabelled: isWhiteLabelled })
        },
        reportDashboardTileRepositioned: async ({ dashboardId, action, layoutZoom }) => {
            posthog.capture('dashboard tile repositioned', {
                dashboard_id: dashboardId,
                action,
                layout_zoom: layoutZoom,
            })
        },
        reportDashboardInsightMetaUpdated: async ({ dashboardId, insightId, attribute }) => {
            posthog.capture('dashboard insight meta updated', {
                dashboard_id: dashboardId,
                insight_id: insightId,
                attribute,
            })
        },
        reportDashboardInsightValuesOnSeriesToggled: async ({ dashboardId, insightId, source }) => {
            posthog.capture('dashboard insight values on series toggled', {
                dashboard_id: dashboardId,
                insight_id: insightId,
                source,
            })
        },
        reportDashboardInsightLegendToggled: async ({ dashboardId, insightId, source }) => {
            posthog.capture('dashboard insight legend toggled', {
                dashboard_id: dashboardId,
                insight_id: insightId,
                source,
            })
        },
        reportDashboardEmptyAiPromptClicked: async ({ promptLabel, dashboardId }) => {
            posthog.capture('dashboard empty ai prompt clicked', {
                prompt_label: promptLabel,
                dashboard_id: dashboardId,
                source: 'web',
            })
        },
        reportUpgradeModalShown: async (payload) => {
            posthog.capture('upgrade modal shown', payload)
        },
        reportTimezoneComponentViewed: async (payload) => {
            posthog.capture('timezone component viewed', payload)
        },
        reportTestAccountFiltersUpdated: async ({ filters }) => {
            const payload = {
                filters_count: filters.length,
                filters: filters.map((filter) => {
                    return { key: filter.key, operator: filter.operator, value_length: filter.value.length }
                }),
            }
            posthog.capture('test account filters updated', payload)
        },
        reportPoEModeUpdated: async ({ mode }) => {
            posthog.capture('persons on events mode updated', { mode })
        },
        reportPersonJoinModeUpdated: async ({ mode }) => {
            posthog.capture('persons join mode updated', { mode })
        },
        reportBounceRatePageViewModeUpdated: async ({ mode }) => {
            posthog.capture('bounce rate page view mode updated', { mode })
        },
        reportSessionTableVersionUpdated: async ({ version }) => {
            posthog.capture('session table version updated', { version })
        },
        reportCustomChannelTypeRulesUpdated: async ({ numRules }) => {
            posthog.capture('custom channel type rules updated', { numRules })
        },
        reportInsightFilterRemoved: async ({ index }) => {
            posthog.capture('local filter removed', { index })
        },
        reportInsightFilterAdded: async ({ newLength }) => {
            posthog.capture('filter added', { newLength })
        },
        reportInsightFilterSet: async ({ filters }) => {
            posthog.capture('filters set', { filters })
        },
        reportInsightWhitelabelToggled: async ({ isWhiteLabelled }) => {
            posthog.capture(`insight whitelabel toggled`, { is_whitelabelled: isWhiteLabelled })
        },
        reportEntityFilterVisibilitySet: async ({ index, visible, entityName }) => {
            posthog.capture('entity filter visbility set', { index, visible, entityName })
        },
        reportPropertySelectOpened: async () => {
            posthog.capture('property select toggle opened')
        },
        reportCreatedDashboardFromModal: async () => {
            posthog.capture('created new dashboard from modal')
        },
        reportWebDashboardCreatedFromTemplate: async (payload) => {
            posthog.capture('dashboard created from template', {
                ...payload,
            })
        },
        reportSavedInsightToDashboard: async ({ insight, dashboardId }) => {
            posthog.capture('saved insight to dashboard', {
                insight: sanitizeInsight(insight),
                dashboard_id: dashboardId,
            })
        },
        reportRemovedInsightFromDashboard: async ({ insight, dashboardId }) => {
            posthog.capture('removed insight from dashboard', {
                insight: sanitizeInsight(insight),
                dashboard_id: dashboardId,
            })
        },
        reportCopiedDashboardTileToDashboard: async ({ fromDashboardId, toDashboardId, tileType }) => {
            posthog.capture('dashboard widget copied to other dashboard', {
                from_dashboard_id: fromDashboardId,
                to_dashboard_id: toDashboardId,
                tile_type: tileType,
            })
        },
        reportInsightsTableCalcToggled: async (payload) => {
            posthog.capture('insights table calc toggled', payload)
        },
        reportSavedInsightFilterUsed: ({ filterKeys }) => {
            posthog.capture('saved insights list page filter used', { filter_keys: filterKeys })
        },
        reportSavedInsightTabChanged: ({ tab }) => {
            posthog.capture('saved insights list page tab changed', { tab })
        },
        reportSavedInsightNewInsightClicked: ({ insightType }) => {
            posthog.capture('saved insights new insight clicked', { insight_type: insightType })
        },
        reportPersonSplit: (props) => {
            posthog.capture('split person started', props)
        },
        reportHelpButtonViewed: () => {
            posthog.capture('help button viewed')
        },
        reportHelpButtonUsed: (props) => {
            posthog.capture('help button used', props)
        },
        reportCorrelationInteraction: ({ correlationType, action, props }) => {
            posthog.capture('correlation interaction', { correlation_type: correlationType, action, ...props })
        },
        reportCorrelationViewed: ({ delay, query, propertiesTable }) => {
            const payload = sanitizeQuery(query)
            if (delay === 0) {
                posthog.capture(`correlation${propertiesTable ? ' properties' : ''} viewed`, payload)
            } else {
                posthog.capture(`correlation${propertiesTable ? ' properties' : ''} analyzed`, {
                    ...payload,
                    delay,
                })
            }
        },
        reportExperimentWizardStarted: ({ guideVisible }) => {
            posthog.capture('experiment wizard started', {
                guide_visible: guideVisible,
            })
        },
        reportExperimentWizardGuideToggled: ({ visible, currentStep }) => {
            posthog.capture('experiment wizard guide toggled', {
                visible,
                current_step: currentStep,
            })
        },
        reportExperimentCreated: ({ experiment, metadata }) => {
            posthog.capture('experiment created', {
                id: experiment.id,
                name: experiment.name,
                type: experiment.type,
                parameters: experiment.parameters,
                ...metadata,
            })
        },
        reportExperimentUpdated: ({ experiment }) => {
            posthog.capture('experiment updated', {
                ...getEventPropertiesForExperiment(experiment),
            })
        },
        reportExperimentViewed: ({ experiment, duration }) => {
            posthog.capture('experiment viewed', {
                ...getEventPropertiesForExperiment(experiment),
                duration,
            })
        },
        reportExperimentInconsistencyWarningShown: ({ experiment, warningKey }) => {
            posthog.capture('experiment inconsistency warning shown', {
                ...getEventPropertiesForExperiment(experiment),
                warning_key: warningKey,
            })
        },
        reportExperimentMetricsRefreshed: ({ experiment, forceRefresh, context }) => {
            posthog.capture('experiment metrics refreshed', {
                ...getEventPropertiesForExperiment(experiment),
                force_refresh: forceRefresh,
                triggered_by: context?.triggered_by || 'manual',
                auto_refresh_enabled: context?.auto_refresh_enabled,
                auto_refresh_interval: context?.auto_refresh_interval,
            })
        },
        reportExperimentAutoRefreshToggled: ({ experiment, enabled, interval }) => {
            posthog.capture('experiment auto refresh toggled', {
                ...getEventPropertiesForExperiment(experiment),
                enabled,
                interval,
            })
        },
        reportExperimentMetricBreakdownAdded: ({ experiment, metricUuid, breakdown, isPrimary }) => {
            posthog.capture('experiment metric breakdown added', {
                ...getEventPropertiesForExperiment(experiment),
                metric_uuid: metricUuid,
                breakdown_type: breakdown.type,
                breakdown_property: breakdown.property,
                is_primary_metric: isPrimary,
            })
        },
        reportExperimentMetricBreakdownRemoved: ({ experiment, metricUuid, breakdown, index, isPrimary }) => {
            posthog.capture('experiment metric breakdown removed', {
                ...getEventPropertiesForExperiment(experiment),
                metric_uuid: metricUuid,
                breakdown_type: breakdown.type,
                breakdown_property: breakdown.property,
                breakdown_index: index,
                is_primary_metric: isPrimary,
            })
        },
        reportExperimentStartDateChange: ({ experiment, newStartDate }) => {
            posthog.capture('experiment start date changed', {
                ...getEventPropertiesForExperiment(experiment),
                old_start_date: experiment.start_date,
                new_start_date: newStartDate,
            })
        },
        reportExperimentEndDateChange: ({ experiment, newEndDate }) => {
            posthog.capture('experiment end date changed', {
                ...getEventPropertiesForExperiment(experiment),
                old_end_date: experiment.end_date,
                new_end_date: newEndDate,
            })
        },
        reportExperimentExposureCohortCreated: ({ experiment, cohort }) => {
            posthog.capture('experiment exposure cohort created', {
                experiment_id: experiment.id,
                cohort_filters: cohort.filters,
            })
        },
        reportExperimentExposureCohortEdited: ({ existingCohort, newCohort }) => {
            posthog.capture('experiment exposure cohort edited', {
                existing_filters: existingCohort.filters,
                new_filters: newCohort.filters,
                id: newCohort.id,
            })
        },
        reportExperimentInsightLoadFailed: () => {
            posthog.capture('experiment load insight failed')
        },
        reportExperimentVariantScreenshotUploaded: ({ experimentId }) => {
            posthog.capture('experiment variant screenshot uploaded', {
                experiment_id: experimentId,
            })
        },
        reportExperimentResultsLoadingTimeout: ({ experimentId }) => {
            posthog.capture('experiment results loading timeout', {
                experiment_id: experimentId,
            })
        },
        reportExperimentReleaseConditionsViewed: ({ experimentId }) => {
            posthog.capture('experiment release conditions viewed', {
                experiment_id: experimentId,
            })
        },
        reportExperimentReleaseConditionsUpdated: ({ experimentId }) => {
            posthog.capture('experiment release conditions updated', {
                experiment_id: experimentId,
            })
        },
        reportExperimentHoldoutCreated: ({ holdout }) => {
            posthog.capture('experiment holdout created', {
                name: holdout.name,
                holdout_id: holdout.id,
                filters: holdout.filters,
            })
        },
        reportExperimentHoldoutAssigned: ({ experimentId, holdoutId }) => {
            posthog.capture('experiment holdout assigned', {
                experiment_id: experimentId,
                holdout_id: holdoutId,
            })
        },
        reportExperimentSharedMetricCreated: ({ sharedMetric }) => {
            posthog.capture('experiment shared metric created', {
                name: sharedMetric.name,
                id: sharedMetric.id,
                ...getEventPropertiesForMetric(sharedMetric.query as ExperimentTrendsQuery | ExperimentFunnelsQuery),
            })
        },
        reportExperimentSharedMetricAssigned: ({ experimentId, sharedMetric }) => {
            posthog.capture('experiment shared metric assigned', {
                experiment_id: experimentId,
                name: sharedMetric.name,
                id: sharedMetric.id,
                ...getEventPropertiesForMetric(sharedMetric.query as ExperimentTrendsQuery | ExperimentFunnelsQuery),
            })
        },
        reportExperimentDashboardCreated: ({ experiment, dashboardId }) => {
            posthog.capture('experiment dashboard created', {
                experiment_name: experiment.name,
                experiment_id: experiment.id,
                dashboard_id: dashboardId,
            })
        },
        reportExperimentMetricFinished: ({ experimentId, metric, teamId, queryId, context }) => {
            posthog.capture('experiment metric finished', {
                experiment_id: experimentId,
                team_id: teamId,
                query_id: queryId,
                ...getEventPropertiesForMetric(metric),
                metric,
                ...context,
            })
        },
        reportExperimentMetricError: ({ experimentId, metric, teamId, queryId, context }) => {
            posthog.capture('experiment metric error', {
                experiment_id: experimentId,
                team_id: teamId,
                query_id: queryId,
                ...getEventPropertiesForMetric(metric),
                ...context,
            })
        },
        reportExperimentResultsRefreshCompleted: ({ experimentId, teamId, context }) => {
            posthog.capture('experiment results refresh completed', {
                experiment_id: experimentId,
                team_id: teamId,
                ...context,
            })
        },
        reportExperimentFeatureFlagModalOpened: () => {
            posthog.capture('experiment feature flag modal opened')
        },
        reportExperimentFeatureFlagSelected: ({ featureFlagKey }: { featureFlagKey: string }) => {
            posthog.capture('experiment feature flag selected', { feature_flag_key: featureFlagKey })
        },
        reportExperimentTimeseriesViewed: ({
            experimentId,
            metric,
        }: {
            experimentId: ExperimentIdType
            metric: ExperimentMetric
        }) => {
            posthog.capture('experiment timeseries viewed', { experiment_id: experimentId, metric })
        },
        reportExperimentTimeseriesRecalculated: ({
            experimentId,
            metric,
        }: {
            experimentId: ExperimentIdType
            metric: ExperimentMetric
        }) => {
            posthog.capture('experiment timeseries recalculated', { experiment_id: experimentId, metric })
        },
        reportExperimentAiSummaryRequested: ({ experiment }) => {
            posthog.capture('experiment ai summary requested', {
                ...getEventPropertiesForExperiment(experiment),
            })
        },
        reportExperimentSessionReplaySummaryRequested: ({ experiment }) => {
            posthog.capture('experiment session replay summary requested', {
                ...getEventPropertiesForExperiment(experiment),
            })
        },
        reportPropertyGroupFilterAdded: () => {
            posthog.capture('property group filter added')
        },
        reportPropertyGroupFilterRemoved: () => {
            posthog.capture('property group filter removed')
        },
        reportPropertyGroupFilterDuplicated: () => {
            posthog.capture('property group filter duplicated')
        },
        reportInsightDateRangeChanged: ({ queryKind }) => {
            posthog.capture('insight date range changed', { query_kind: queryKind })
        },
        reportInsightBreakdownChanged: ({ queryKind }) => {
            posthog.capture('insight breakdown changed', { query_kind: queryKind })
        },
        reportInsightCompareChanged: ({ queryKind }) => {
            posthog.capture('insight compare changed', { query_kind: queryKind })
        },
        reportChangeOuterPropertyGroupFiltersType: ({ type, groupsLength }) => {
            posthog.capture('outer match property groups type changed', { type, groupsLength })
        },
        reportChangeInnerPropertyGroupFiltersType: ({ type, filtersLength }) => {
            posthog.capture('inner match property group filters type changed', { type, filtersLength })
        },
        reportTaxonomicFilterCategorySelected: ({ groupType, eventName }) => {
            posthog.capture('taxonomic filter category selected', { groupType, eventName })
        },
        reportTaxonomicFilterAddFilterClicked: ({ eventName }) => {
            posthog.capture('taxonomic filter add filter clicked', { eventName })
        },
        reportMissingTaxonomyEntries: ({ entries }) => {
            for (const { name, groupType } of entries) {
                const key = `${groupType}::${name}`
                if (reportedMissingTaxonomyEntries.has(key)) {
                    continue
                }
                reportedMissingTaxonomyEntries.add(key)
                posthog.capture('taxonomy entry missing', {
                    name,
                    group_type: groupType,
                    source: 'taxonomic_filter',
                })
            }
        },
        reportDataManagementDefinitionHovered: ({ type, mediaPreviewCount }) => {
            posthog.capture('definition hovered', { type, media_preview_count: mediaPreviewCount ?? 0 })
        },
        reportMediaPreviewUploaded: ({ source }) => {
            posthog.capture('media preview uploaded', { source })
        },
        reportDataManagementDefinitionClickView: ({ type }) => {
            posthog.capture('definition click view', { type })
        },
        reportDataManagementDefinitionClickEdit: ({ type }) => {
            posthog.capture('definition click edit', { type })
        },
        reportDataManagementDefinitionSaveSucceeded: ({ type, loadTime }) => {
            posthog.capture('definition save succeeded', { type, load_time: loadTime })
        },
        reportDataManagementDefinitionSaveFailed: ({ type, loadTime, error }) => {
            posthog.capture('definition save failed', { type, load_time: loadTime, error })
        },
        reportDataManagementDefinitionCancel: ({ type }) => {
            posthog.capture('definition cancelled', { type })
        },
        reportDataManagementEventDefinitionsPageLoadSucceeded: ({ loadTime, resultsLength }) => {
            posthog.capture('event definitions page load succeeded', {
                load_time: loadTime,
                num_results: resultsLength,
            })
        },
        reportDataManagementEventDefinitionsPageLoadFailed: ({ loadTime, error }) => {
            posthog.capture('event definitions page load failed', { load_time: loadTime, error })
        },
        reportDataManagementEventDefinitionsPageNestedPropertiesLoadSucceeded: ({ loadTime }) => {
            posthog.capture('event definitions page event nested properties load succeeded', { load_time: loadTime })
        },
        reportDataManagementEventDefinitionsPageNestedPropertiesLoadFailed: ({ loadTime, error }) => {
            posthog.capture('event definitions page event nested properties load failed', {
                load_time: loadTime,
                error,
            })
        },
        reportDataManagementEventPropertyDefinitionsPageLoadSucceeded: ({ loadTime, resultsLength }) => {
            posthog.capture('event property definitions page load succeeded', {
                load_time: loadTime,
                num_results: resultsLength,
            })
        },
        reportDataManagementEventPropertyDefinitionsPageLoadFailed: ({ loadTime, error }) => {
            posthog.capture('event property definitions page load failed', {
                load_time: loadTime,
                error,
            })
        },
        reportInsightOpenedFromRecentInsightList: () => {
            posthog.capture('insight opened from recent insight list')
        },
        reportPersonOpenedFromNewlySeenPersonsList: () => {
            posthog.capture('person opened from newly seen persons list')
        },
        reportIngestionContinueWithoutVerifying: () => {
            posthog.capture('ingestion continue without verifying')
        },
        reportAutocaptureToggled: ({ autocapture_opt_out }) => {
            posthog.capture('autocapture toggled', {
                autocapture_opt_out,
            })
        },
        reportAutocaptureExceptionsToggled: ({ autocapture_opt_in }) => {
            posthog.capture('autocapture exceptions toggled', {
                autocapture_opt_in,
            })
        },
        reportHeatmapsToggled: ({ heatmaps_opt_in }) => {
            posthog.capture('heatmaps toggled', {
                heatmaps_opt_in,
            })
        },
        reportActivityLogSettingToggled: ({ receive_org_level_activity_logs }) => {
            posthog.capture('activity log org level setting toggled', {
                receive_org_level_activity_logs,
            })
        },
        reportFailedToCreateFeatureFlagWithCohort: ({ detail, code }) => {
            posthog.capture('failed to create feature flag with cohort', { detail, code })
        },
        reportFeatureFlagCopySuccess: () => {
            posthog.capture('feature flag copied')
        },
        reportFeatureFlagCopyFailure: ({ error }) => {
            posthog.capture('feature flag copy failure', { error })
        },
        reportFeatureFlagScheduleSuccess: () => {
            posthog.capture('feature flag scheduled')
        },
        reportFeatureFlagScheduleFailure: ({ error }) => {
            posthog.capture('feature flag schedule failure', { error })
        },
        reportInviteMembersButtonClicked: () => {
            posthog.capture('invite members button clicked')
        },
        reportTeamSettingChange: ({ name, value }) => {
            posthog.capture(`${name} team setting updated`, {
                setting: name,
                value,
            })
        },
        reportProjectSettingChange: ({ name, value }) => {
            posthog.capture(`${name} project setting updated`, {
                setting: name,
                value,
            })
        },
        reportActivationSideBarTaskClicked: ({ key }) => {
            posthog.capture('activation sidebar task clicked', {
                key,
            })
        },
        reportBillingUpgradeClicked: ({ plan }) => {
            posthog.capture('billing upgrade button clicked', {
                plan,
            })
        },
        reportBillingDowngradeClicked: ({ plan }) => {
            posthog.capture('billing downgrade button clicked', {
                plan,
            })
        },
        reportBillingAddonPlanSwitchStarted: ({ fromProduct, toProduct, reason }) => {
            const eventName =
                reason === 'upgrade'
                    ? 'billing addon subscription upgrade clicked'
                    : 'billing addon subscription downgrade clicked'
            posthog.capture(eventName, {
                from_product: fromProduct,
                to_product: toProduct,
            })
        },
        reportRoleCreated: ({ role }) => {
            posthog.capture('new role created', {
                role,
            })
        },
        reportResourceAccessLevelUpdated: ({ resourceType, roleName, accessLevel }) => {
            posthog.capture('resource access level updated', {
                resource_type: resourceType,
                role_name: roleName,
                access_level: accessLevel,
            })
        },
        reportRoleCustomAddedToAResource: ({ resourceType, rolesLength }) => {
            posthog.capture('role custom added to a resource', {
                resource_type: resourceType,
                roles_length: rolesLength,
            })
        },
        reportGroupViewSaved: ({ groupTypeIndex, shortcutName }) => {
            posthog.capture('group view saved', {
                group_type_index: groupTypeIndex,
                shortcut_name: shortcutName,
            })
        },
        reportFlagsCodeExampleInteraction: ({ optionType }) => {
            posthog.capture('flags code example option selected', {
                option_type: optionType,
            })
        },
        reportFlagsCodeExampleLanguage: ({ language }) => {
            posthog.capture('flags code example language selected', {
                language,
            })
        },
        reportSurveyCreated: ({ survey, isDuplicate, creationSource }) => {
            const questionsWithShuffledOptions = survey.questions.filter((question) => {
                return question.hasOwnProperty('shuffleOptions') && (question as MultipleSurveyQuestion).shuffleOptions
            })

            posthog.capture('survey created', {
                name: survey.name,
                id: survey.id,
                survey_type: survey.type,
                questions_length: survey.questions.length,
                question_types: survey.questions.map((question) => question.type),
                is_duplicate: isDuplicate ?? false,
                creation_source: creationSource ?? 'full_editor',
                linked_insight_id: survey.linked_insight_id,
                events_count: survey.conditions?.events?.values.length,
                recurring_survey_iteration_count: survey.iteration_count == undefined ? 0 : survey.iteration_count,
                recurring_survey_iteration_interval:
                    survey.iteration_frequency_days == undefined ? 0 : survey.iteration_frequency_days,
                shuffle_questions_enabled: !!survey.appearance?.shuffleQuestions,
                shuffle_question_options_enabled_count: questionsWithShuffledOptions.length,
                has_branching_logic: survey.questions.some(
                    (question) => question.branching && Object.keys(question.branching).length > 0
                ),
                has_partial_responses: survey.enable_partial_responses,
                skipping_submit_button: survey.questions.some((question) => {
                    if (
                        question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice
                    ) {
                        return question.skipSubmitButton
                    }
                    return false
                }),
            })
        },
        reportSurveyViewed: ({ survey }) => {
            posthog.capture('survey viewed', {
                name: survey.name,
                id: survey.id,
                created_at: survey.created_at,
                start_date: survey.start_date,
                end_date: survey.end_date,
            })
        },
        reportSurveyArchived: ({ survey }) => {
            posthog.capture('survey archived', {
                name: survey.name,
                id: survey.id,
                created_at: survey.created_at,
                start_date: survey.start_date,
                end_date: survey.end_date,
            })
        },
        reportSurveyEdited: ({ survey }) => {
            const questionsWithShuffledOptions = survey.questions.filter((question) => {
                return question.hasOwnProperty('shuffleOptions') && (question as MultipleSurveyQuestion).shuffleOptions
            })

            posthog.capture('survey edited', {
                name: survey.name,
                id: survey.id,
                created_at: survey.created_at,
                start_date: survey.start_date,
                events_count: survey.conditions?.events?.values.length,
                recurring_survey_iteration_count: survey.iteration_count == undefined ? 0 : survey.iteration_count,
                recurring_survey_iteration_interval:
                    survey.iteration_frequency_days == undefined ? 0 : survey.iteration_frequency_days,
                shuffle_questions_enabled: !!survey.appearance?.shuffleQuestions,
                shuffle_question_options_enabled_count: questionsWithShuffledOptions.length,
                has_branching_logic: survey.questions.some(
                    (question) => question.branching && Object.keys(question.branching).length > 0
                ),
                has_partial_responses: survey.enable_partial_responses,
                skipping_submit_button: survey.questions.some((question) => {
                    if (
                        question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice
                    ) {
                        return question.skipSubmitButton
                    }
                    return false
                }),
            })
        },
        reportSurveyTemplateClicked: ({ template, source }) => {
            posthog.capture('survey template clicked', {
                template,
                source,
            })
        },
        reportSurveyEmptyStateViewed: () => {
            posthog.capture('survey empty state viewed')
        },
        reportSurveyAiPromptSubmitted: ({ source }) => {
            posthog.capture('survey AI prompt submitted', {
                source,
            })
        },
        reportSurveyCycleDetected: ({ survey }) => {
            posthog.capture('survey cycle detected', {
                name: survey.name,
                id: survey.id,
                start_date: survey.start_date,
                end_date: survey.end_date,
            })
        },
        reportSurveyConsolidatedResultsQuery: ({ survey, totalDurationMs, queryDurations }) => {
            posthog.capture('survey consolidated results query completed', {
                name: survey.name,
                id: survey.id,
                duration: totalDurationMs,
                aggregate_duration: queryDurations.aggregate,
                open_ended_duration: queryDurations.openEnded,
            })
        },
        reportProductTourViewed: ({ tour }) => {
            posthog.capture(ProductTourEvent.VIEWED, {
                tour_id: tour.id,
                tour_name: tour.name,
                tour_type: tour.content?.type ?? 'tour',
                step_count: tour.content?.steps?.length ?? 0,
                start_date: tour.start_date,
                end_date: tour.end_date,
            })
        },
        reportProductTourCreated: ({ tour, creationSource }) => {
            posthog.capture(ProductTourEvent.CREATED, {
                tour_id: tour.id,
                tour_name: tour.name,
                tour_type: tour.content?.type ?? 'tour',
                step_count: tour.content?.steps?.length ?? 0,
                has_targeting: !!tour.internal_targeting_flag,
                auto_launch: tour.auto_launch,
                creation_source: creationSource ?? 'app',
            })
        },
        reportProductTourListViewed: () => {
            posthog.capture(ProductTourEvent.LIST_VIEWED)
        },
        reportUserFeedbackButtonClicked: ({ source, meta }) => {
            posthog.capture('feedback button clicked', {
                source,
                ...meta,
            })
        },
        reportProductUnsubscribed: ({ product }) => {
            const property_key = `unsubscribed_from_${product}`
            posthog.capture('product unsubscribed', {
                product,
                $set: { [property_key]: true },
            })
        },
        // onboarding
        reportSubscribedDuringOnboarding: ({ productKey }) => {
            posthog.capture('subscribed during onboarding', {
                product_key: productKey,
            })
        },
        reportOnboardingStarted: ({ entrypoint }) => {
            posthog.capture('onboarding started', {
                entry_point: entrypoint,
            })
        },
        reportOnboardingStepCompleted: ({ stepKey }) => {
            posthog.capture('onboarding step completed', {
                step_key: stepKey,
            })
        },
        reportOnboardingStepSkipped: ({ stepKey }) => {
            posthog.capture('onboarding step skipped', {
                step_key: stepKey,
            })
        },
        reportOnboardingCompleted: ({ productKey }) => {
            posthog.capture('onboarding completed', {
                product_key: productKey,
            })
        },
        reportOnboardingUseCaseSelected: ({ useCase, recommendedProducts }) => {
            posthog.capture('onboarding use case selected', {
                use_case: useCase,
                recommended_products: recommendedProducts,
            })
        },
        reportOnboardingUseCaseSkipped: () => {
            posthog.capture('onboarding use case skipped')
        },
        reportOnboardingProductSelectionPath: ({ path, properties }) => {
            posthog.capture('onboarding product selection path', {
                path,
                use_case: properties?.useCase,
                recommended_products: properties?.recommendedProducts,
                has_browsing_history: properties?.hasBrowsingHistory,
            })
        },
        reportAIChatOnboardingStarted: ({ variant }) => {
            posthog.capture('ai chat onboarding started', {
                variant,
            })
        },
        reportAIChatOnboardingMessageSent: ({ stepKey, messageType }) => {
            posthog.capture('ai chat onboarding message sent', {
                step_key: stepKey,
                message_type: messageType,
            })
        },
        reportAIChatOnboardingStepTime: ({ stepKey, timeSeconds }) => {
            posthog.capture('ai chat onboarding step time', {
                step_key: stepKey,
                time_seconds: timeSeconds,
            })
        },
        reportOnboardingProductToggled: ({ productKey, selected, recommendationSource }) => {
            posthog.capture('onboarding product toggled', {
                product_key: productKey,
                selected,
                recommendation_source: recommendationSource,
            })
        },
        reportSDKSelected: ({ sdk }) => {
            posthog.capture('sdk selected', {
                sdk: sdk.key,
            })
        },
        // command bar
        reportCommandBarStatusChanged: ({ status }) => {
            posthog.capture('command bar status changed', { status })
        },
        reportCommandBarSearch: ({ queryLength }) => {
            posthog.capture('command bar search', { queryLength })
        },
        reportCommandBarSearchResultOpened: ({ type }) => {
            posthog.capture('command bar search result opened', { type })
        },
        reportCommandBarActionSearch: ({ query }) => {
            posthog.capture('command bar action search', { query })
        },
        reportCommandBarActionResultExecuted: ({ resultDisplay }) => {
            posthog.capture('command bar search result executed', { resultDisplay })
        },
        reportAccountOwnerClicked: ({ name, email }) => {
            posthog.capture('account owner clicked', { name, email })
        },
        // revenue analytics
        reportRevenueAnalyticsViewed: async ({ delay }, breakpoint) => {
            if (!delay) {
                await breakpoint(500)
            }
            const eventName = delay ? 'revenue analytics analyzed' : 'revenue analytics viewed'
            posthog.capture(eventName, { delay })
        },
        reportRevenueAnalyticsSettingsViewed: () => {
            posthog.capture('revenue analytics settings viewed')
        },
        reportRevenueAnalyticsOnboardingViewed: () => {
            posthog.capture('revenue analytics onboarding viewed')
        },
        reportRevenueAnalyticsOnboardingCompleted: ({ hasEvents, hasSources }) => {
            posthog.capture('revenue analytics onboarding completed', {
                has_events: hasEvents,
                has_sources: hasSources,
            })
        },
        reportRevenueAnalyticsEventCreated: ({ eventName }) => {
            posthog.capture('revenue analytics event created', { event_name: eventName })
        },
        reportRevenueAnalyticsEventDeleted: ({ eventName }) => {
            posthog.capture('revenue analytics event deleted', { event_name: eventName })
        },
        reportRevenueAnalyticsEventEdited: ({ eventName }) => {
            posthog.capture('revenue analytics event edited', { event_name: eventName })
        },
        reportRevenueAnalyticsDataSourceConnected: async ({ sourceType }) => {
            posthog.capture('revenue analytics data source connected', { source_type: sourceType })
        },
        reportRevenueAnalyticsDataSourceEnabled: ({ sourceType }) => {
            posthog.capture('revenue analytics data source enabled', { source_type: sourceType })
        },
        reportRevenueAnalyticsDataSourceDisabled: ({ sourceType }) => {
            posthog.capture('revenue analytics data source disabled', { source_type: sourceType })
        },
        reportRevenueAnalyticsFilterApplied: ({ filterCount }) => {
            posthog.capture('revenue analytics filter applied', { filter_count: filterCount })
        },
        reportRevenueAnalyticsBreakdownAdded: ({ breakdownProperty, breakdownType }) => {
            posthog.capture('revenue analytics breakdown added', {
                breakdown_property: breakdownProperty,
                breakdown_type: breakdownType,
            })
        },
        reportRevenueAnalyticsBreakdownRemoved: ({ breakdownProperty, breakdownType }) => {
            posthog.capture('revenue analytics breakdown removed', {
                breakdown_property: breakdownProperty,
                breakdown_type: breakdownType,
            })
        },
        reportRevenueAnalyticsDateRangeChanged: ({ dateFrom, dateTo }) => {
            posthog.capture('revenue analytics date range changed', {
                date_from: dateFrom,
                date_to: dateTo,
            })
        },
        reportRevenueAnalyticsMRRModeChanged: ({ mrrMode }) => {
            posthog.capture('revenue analytics MRR mode changed', { mrr_mode: mrrMode })
        },
        reportRevenueAnalyticsMRRBreakdownModalOpened: () => {
            posthog.capture('revenue analytics MRR breakdown modal opened')
        },
        reportRevenueAnalyticsGoalConfigured: () => {
            posthog.capture('revenue analytics goal configured')
        },
        reportRevenueAnalyticsTestAccountFilterUpdated: ({ filterTestAccounts }) => {
            posthog.capture('revenue analytics test account filter updated', {
                filter_test_accounts: filterTestAccounts,
            })
        },
        reportMarketingAnalyticsOnboardingViewed: () => {
            posthog.capture('marketing analytics onboarding viewed')
        },
        reportMarketingAnalyticsOnboardingCompleted: ({ hasSources }) => {
            posthog.capture('marketing analytics onboarding completed', {
                has_sources: hasSources,
            })
        },
        reportMarketingAnalyticsDataSourceConnected: ({ sourceType }) => {
            posthog.capture('marketing analytics data source connected', { source_type: sourceType })
        },
        reportWebAnalyticsHealthStatus: ({ props }) => {
            posthog.capture('web analytics health status', props)
        },
        reportWebAnalyticsHealthTabViewed: ({ props }) => {
            posthog.capture('web analytics health tab viewed', props)
        },
        reportWebAnalyticsHealthSectionToggled: ({ props }) => {
            posthog.capture('web analytics health section toggled', props)
        },
        reportWebAnalyticsHealthActionClicked: ({ props }) => {
            posthog.capture('web analytics health action clicked', props)
        },
        reportWebAnalyticsHealthRefreshed: ({ props }) => {
            posthog.capture('web analytics health refreshed', props)
        },
        reportWebAnalyticsFilterApplied: ({ props }) => {
            posthog.capture('web analytics filter applied', props)
        },
        reportWebAnalyticsFilterRemoved: ({ props }) => {
            posthog.capture('web analytics filter removed', props)
        },
        reportWebAnalyticsDateRangeChanged: ({ props }) => {
            posthog.capture('web analytics date range changed', props)
        },
        reportWebAnalyticsCompareToggled: ({ props }) => {
            posthog.capture('web analytics compare toggled', props)
        },
        reportWebAnalyticsConversionGoalSet: ({ props }) => {
            posthog.capture('web analytics conversion goal set', props)
        },
        reportWebAnalyticsPathCleaningToggled: ({ props }) => {
            posthog.capture('web analytics path cleaning toggled', props)
        },
        // Customer Analytics
        reportCustomerAnalyticsDashboardBusinessModeChanged: async ({ business_mode }) => {
            posthog.capture('customer analytics dashboard business mode changed', { business_mode })
        },
        reportCustomerAnalyticsDashboardConfigurationButtonClicked: async () => {
            posthog.capture('customer analytics dashboard configuration button clicked')
        },
        reportCustomerAnalyticsDashboardConfigurationViewed: async (_, breakpoint) => {
            await breakpoint(500)
            posthog.capture('customer analytics dashboard configuration viewed')
        },
        reportCustomerAnalyticsDashboardDateFilterApplied: async ({ filter }) => {
            posthog.capture('customer analytics dashboard date filter applied', { filter })
        },
        reportCustomerAnalyticsDashboardEventPickerClicked: async ({ event }) => {
            posthog.capture('customer analytics dashboard event picker clicked', { event })
        },
        reportCustomerAnalyticsDashboardConfigureEventWithAIClicked: async ({ event }) => {
            posthog.capture('customer analytics dashboard configure event with AI clicked', { event })
        },
        reportCustomerAnalyticsAddJoinButtonClicked: async ({ table }) => {
            posthog.capture('customer analytics add join button clicked', { table })
        },
        reportCustomerAnalyticsDashboardEventsSaved: async () => {
            posthog.capture('customer analytics dashboard events saved')
        },
        reportUsageMetricsSettingsViewed: async (_, breakpoint) => {
            await breakpoint(500)
            posthog.capture('usage metrics settings viewed')
        },
        reportUsageMetricsCreateButtonClicked: async () => {
            posthog.capture('usage metrics create button clicked')
        },
        reportUsageMetricsUpdateButtonClicked: async () => {
            posthog.capture('usage metrics update button clicked')
        },
        reportUsageMetricCreated: async () => {
            posthog.capture('usage metric created')
        },
        reportUsageMetricUpdated: async () => {
            posthog.capture('usage metric updated')
        },
        reportUsageMetricDeleted: async () => {
            posthog.capture('usage metric deleted')
        },
        reportCustomerAnalyticsViewed: async ({ delay }, breakpoint) => {
            if (!delay) {
                await breakpoint(500)
            }
            const eventName = delay ? 'customer analytics analyzed' : 'customer analytics viewed'
            posthog.capture(eventName, { delay })
        },
        // Customer Journeys
        reportCustomerJourneyViewed: async ({ journeyId, journeyName, stepCount, delay }, breakpoint) => {
            if (!delay) {
                await breakpoint(500)
            }
            const eventName = delay ? 'customer journey analyzed' : 'customer journey viewed'
            posthog.capture(eventName, {
                journey_id: journeyId,
                journey_name: journeyName,
                step_count: stepCount,
                delay,
            })
        },
        reportCustomerJourneyCreated: async ({ journeyName, stepCount, creationSource }) => {
            posthog.capture('customer journey created', {
                journey_name: journeyName,
                step_count: stepCount,
                creation_source: creationSource,
            })
        },
        reportCustomerJourneyUpdated: async ({ journeyId, journeyName, stepCount }) => {
            posthog.capture('customer journey updated', {
                journey_id: journeyId,
                journey_name: journeyName,
                step_count: stepCount,
            })
        },
        reportCustomerJourneyDeleted: async ({ journeyId }) => {
            posthog.capture('customer journey deleted', { journey_id: journeyId })
        },
        reportCustomerJourneyTemplateSelected: async ({ templateKey }) => {
            posthog.capture('customer journey template selected', { template_key: templateKey })
        },
        reportCustomerJourneyExistingFunnelSelected: async ({ insightId }) => {
            posthog.capture('customer journey existing funnel selected', { insight_id: insightId })
        },
        reportCustomerJourneyPathExpanded: async ({ pathType, dropOff, stepIndex }) => {
            posthog.capture('customer journey path expanded', {
                path_type: pathType,
                drop_off: dropOff,
                step_index: stepIndex,
            })
        },
        reportCustomerJourneyStepAddedFromPath: async ({ eventName, pathType, stepIndex }) => {
            posthog.capture('customer journey step added from path', {
                event_name: eventName,
                path_type: pathType,
                step_index: stepIndex,
            })
        },
        reportCustomerJourneyStepsSavedFromEditor: async ({ stepsAdded, journeyId }) => {
            posthog.capture('customer journey steps saved from editor', {
                steps_added: stepsAdded,
                journey_id: journeyId,
            })
        },
        reportCustomerJourneyBuilderStepAdded: async ({ stepIndex, stepCount }) => {
            posthog.capture('customer journey builder step added', {
                step_index: stepIndex,
                step_count: stepCount,
            })
        },
        reportCustomerJourneyBuilderStepRemoved: async ({ stepIndex, stepCount }) => {
            posthog.capture('customer journey builder step removed', {
                step_index: stepIndex,
                step_count: stepCount,
            })
        },
        reportGroupProfileViewed: async ({ delay }, breakpoint) => {
            if (!delay) {
                await breakpoint(500)
            }
            const eventName = delay ? 'group profile analyzed' : 'group profile viewed'
            posthog.capture(eventName, { delay })
        },
        reportPersonProfileViewed: async ({ delay }, breakpoint) => {
            if (!delay) {
                await breakpoint(500)
            }
            const eventName = delay ? 'person profile analyzed' : 'person profile viewed'
            posthog.capture(eventName, { delay })
        },
        reportNavbarStarredItemAdded: ({ itemType, itemName, isAIFirst }) => {
            posthog.capture('navbar starred item added', {
                item_type: itemType,
                item_name: itemName,
                is_ai_first: isAIFirst,
            })
        },
        reportNavbarStarredItemRemoved: ({ itemType, itemName, isAIFirst }) => {
            posthog.capture('navbar starred item removed', {
                item_type: itemType,
                item_name: itemName,
                is_ai_first: isAIFirst,
            })
        },
        reportNavbarStarredItemClicked: ({ itemType, itemName, isAIFirst }) => {
            posthog.capture('navbar starred item clicked', {
                item_type: itemType,
                item_name: itemName,
                is_ai_first: isAIFirst,
            })
        },
    })),
])
