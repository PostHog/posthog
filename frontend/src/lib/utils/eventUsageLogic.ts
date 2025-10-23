import { actions, connect, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import { BarStatus, ResultType } from 'lib/components/CommandBar/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { Dayjs } from 'lib/dayjs'
import { now } from 'lib/dayjs'
import { TimeToSeeDataPayload } from 'lib/internalMetrics'
import { objectClean } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { BillingUsageInteractionProps } from 'scenes/billing/types'
import { SharedMetric } from 'scenes/experiments/SharedMetrics/sharedMetricLogic'
import { NewSurvey, SurveyTemplateType } from 'scenes/surveys/constants'
import { userLogic } from 'scenes/userLogic'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
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
    isDataWarehouseNode,
    isEventsNode,
    isFunnelsQuery,
    isInsightQueryNode,
    isInsightVizNode,
    isNodeWithSource,
} from '~/queries/utils'
import { PROPERTY_KEYS } from '~/taxonomy/taxonomy'
import {
    CohortType,
    DashboardMode,
    DashboardTile,
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
    PersonType,
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

export function getEventPropertiesForMetric(
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
): object {
    if (metric.kind === NodeKind.ExperimentMetric) {
        return {
            kind: NodeKind.ExperimentMetric,
            metric_type: metric.metric_type,
        }
    } else if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        return {
            kind: NodeKind.ExperimentFunnelsQuery,
            steps_count: metric.funnels_query.series.length,
            filter_test_accounts: metric.funnels_query.filterTestAccounts,
        }
    }
    return {
        kind: NodeKind.ExperimentTrendsQuery,
        series_kind: metric.count_query.series[0].kind,
        filter_test_accounts: metric.count_query.filterTestAccounts,
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
        const { dateRange, filterTestAccounts, samplingFactor, properties } = querySource

        // date range and sampling
        payload.date_from = dateRange?.date_from || undefined
        payload.date_to = dateRange?.date_to || undefined
        payload.interval = getInterval(querySource)
        payload.samplingFactor = samplingFactor || undefined

        // series
        payload.series_length = getSeries(querySource)?.length
        payload.event_entity_count = getSeries(querySource)?.filter((e) => isEventsNode(e)).length
        payload.action_entity_count = getSeries(querySource)?.filter((e) => isActionsNode(e)).length
        payload.data_warehouse_entity_count = getSeries(querySource)?.filter((e) => isDataWarehouseNode(e)).length
        payload.has_data_warehouse_series = !!getSeries(querySource)?.find((e) => isDataWarehouseNode(e))

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
        payload.display = getDisplay(querySource)
        payload.compare = getCompareFilter(querySource)?.compare
        payload.compare_to = getCompareFilter(querySource)?.compare_to

        // funnels
        payload.funnel_viz_type = isFunnelsQuery(querySource) ? querySource.funnelsFilter?.funnelVizType : undefined
        payload.funnel_order_type = isFunnelsQuery(querySource) ? querySource.funnelsFilter?.funnelOrderType : undefined
    }

    return objectClean(payload)
}

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
        reportInsightCreated: (query: Node | null) => ({ query }),
        reportInsightSaved: (
            insight: Partial<QueryBasedInsightModel> | null,
            query: Node | null,
            isNewInsight: boolean
        ) => ({ insight, query, isNewInsight }),
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
        reportEntityFilterVisibilitySet: (index: number, visible: boolean) => ({ index, visible }),
        reportInsightsTableCalcToggled: (mode: string) => ({ mode }),
        reportPropertyGroupFilterAdded: true,
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
        reportCorrelationAnalysisFeedback: (rating: number) => ({ rating }),
        reportCorrelationAnalysisDetailedFeedback: (rating: number, comments: string) => ({ rating, comments }),
        reportBookmarkletDragged: true,
        reportProjectCreationSubmitted: (projectCount: number, nameLength: number) => ({ projectCount, nameLength }),
        reportProjectNoticeDismissed: (key: string) => ({ key }),
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
            mode: DashboardMode,
            source: DashboardEventSource | null
        ) => ({ dashboard, mode, source }),
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
        reportSavedInsightToDashboard: (
            insight: Partial<QueryBasedInsightModel> | null,
            dashboardId: number | null
        ) => ({ insight, dashboardId }),
        reportRemovedInsightFromDashboard: (
            insight: Partial<QueryBasedInsightModel> | null,
            dashboardId: number | null
        ) => ({ insight, dashboardId }),
        reportSavedInsightTabChanged: (tab: string) => ({ tab }),
        reportSavedInsightFilterUsed: (filterKeys: string[]) => ({ filterKeys }),
        reportSavedInsightLayoutChanged: (layout: string) => ({ layout }),
        reportSavedInsightNewInsightClicked: (insightType: string) => ({ insightType }),
        reportPersonSplit: (merge_count: number) => ({ merge_count }),
        reportHelpButtonViewed: true,
        reportHelpButtonUsed: (help_type: HelpType) => ({ help_type }),
        reportExperimentArchived: (experiment: Experiment) => ({ experiment }),
        reportExperimentReset: (experiment: Experiment) => ({ experiment }),
        reportExperimentCreated: (experiment: Experiment) => ({ experiment }),
        reportExperimentViewed: (experiment: Experiment, duration: number | null) => ({ experiment, duration }),
        reportExperimentLaunched: (experiment: Experiment, launchDate: Dayjs) => ({ experiment, launchDate }),
        reportExperimentStartDateChange: (experiment: Experiment, newStartDate: string) => ({
            experiment,
            newStartDate,
        }),
        reportExperimentEndDateChange: (experiment: Experiment, newEndDate: string) => ({
            experiment,
            newEndDate,
        }),
        reportExperimentCompleted: (
            experiment: Experiment,
            endDate: Dayjs,
            duration: number,
            significant: boolean
        ) => ({
            experiment,
            endDate,
            duration,
            significant,
        }),
        reportExperimentExposureCohortCreated: (experiment: Experiment, cohort: CohortType) => ({ experiment, cohort }),
        reportExperimentExposureCohortEdited: (existingCohort: CohortType, newCohort: CohortType) => ({
            existingCohort,
            newCohort,
        }),
        reportExperimentInsightLoadFailed: true,
        reportExperimentVariantShipped: (experiment: Experiment) => ({ experiment }),
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
        reportExperimentMetricTimeout: (
            experimentId: ExperimentIdType,
            metric: ExperimentTrendsQuery | ExperimentFunnelsQuery
        ) => ({
            experimentId,
            metric,
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
        // Definition Popover
        reportDataManagementDefinitionHovered: (type: TaxonomicFilterGroupType) => ({ type }),
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
        reportSurveyCreated: (survey: Survey, isDuplicate?: boolean) => ({ survey, isDuplicate }),
        reportSurveyEdited: (survey: Survey) => ({ survey }),
        reportSurveyArchived: (survey: Survey) => ({ survey }),
        reportSurveyTemplateClicked: (template: SurveyTemplateType) => ({ template }),
        reportSurveyCycleDetected: (survey: Survey | NewSurvey) => ({ survey }),
        reportProductUnsubscribed: (product: string) => ({ product }),
        reportSubscribedDuringOnboarding: (productKey: string) => ({ productKey }),
        // command bar
        reportCommandBarStatusChanged: (status: BarStatus) => ({ status }),
        reportCommandBarSearch: (queryLength: number) => ({ queryLength }),
        reportCommandBarSearchResultOpened: (type: ResultType) => ({ type }),
        reportCommandBarActionSearch: (query: string) => ({ query }),
        reportCommandBarActionResultExecuted: (resultDisplay) => ({ resultDisplay }),
        reportBillingCTAShown: true,
        reportBillingUsageInteraction: (properties: BillingUsageInteractionProps) => ({ properties }),
        reportBillingSpendInteraction: (properties: BillingUsageInteractionProps) => ({ properties }),
        reportSDKSelected: (sdk: SDK) => ({ sdk }),
        reportAccountOwnerClicked: ({ name, email }: { name: string; email: string }) => ({ name, email }),
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

            posthog.capture('insight created', sanitizeQuery(query))
        },
        reportInsightSaved: async ({ insight, query, isNewInsight }) => {
            // "insight saved" is a proxy for the new insight's results being valuable to the user
            posthog.capture('insight saved', {
                ...sanitizeQuery(query),
                insight: sanitizeInsight(insight),
                is_new_insight: isNewInsight,
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
            posthog.capture(eventName, objectClean(payload))
        },
        reportPersonsModalViewed: async ({ params }) => {
            posthog.capture('insight person modal viewed', params)
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
            posthog.capture(eventName, properties)
        },
        reportBookmarkletDragged: async (_, breakpoint) => {
            await breakpoint(500)
            posthog.capture('bookmarklet drag start')
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
        reportDashboardModeToggled: async ({ dashboard, mode, source }) => {
            posthog.capture('dashboard mode toggled', {
                dashboard_id: dashboard?.id,
                dashboard: sanitizeDashboard(dashboard),
                mode,
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
        reportEntityFilterVisibilitySet: async ({ index, visible }) => {
            posthog.capture('entity filter visbility set', { index, visible })
        },
        reportPropertySelectOpened: async () => {
            posthog.capture('property select toggle opened')
        },
        reportCreatedDashboardFromModal: async () => {
            posthog.capture('created new dashboard from modal')
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
        reportInsightsTableCalcToggled: async (payload) => {
            posthog.capture('insights table calc toggled', payload)
        },
        reportSavedInsightFilterUsed: ({ filterKeys }) => {
            posthog.capture('saved insights list page filter used', { filter_keys: filterKeys })
        },
        reportSavedInsightTabChanged: ({ tab }) => {
            posthog.capture('saved insights list page tab changed', { tab })
        },
        reportSavedInsightLayoutChanged: ({ layout }) => {
            posthog.capture('saved insights list page layout changed', { layout })
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
        reportCorrelationAnalysisFeedback: (props) => {
            posthog.capture('correlation analysis feedback', props)
        },
        reportCorrelationAnalysisDetailedFeedback: (props) => {
            posthog.capture('correlation analysis detailed feedback', props)
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
        reportExperimentArchived: ({ experiment }) => {
            posthog.capture('experiment archived', {
                ...getEventPropertiesForExperiment(experiment),
            })
        },
        reportExperimentReset: ({ experiment }) => {
            posthog.capture('experiment reset', {
                ...getEventPropertiesForExperiment(experiment),
            })
        },
        reportExperimentCreated: ({ experiment }) => {
            posthog.capture('experiment created', {
                id: experiment.id,
                name: experiment.name,
                type: experiment.type,
                parameters: experiment.parameters,
            })
        },
        reportExperimentViewed: ({ experiment, duration }) => {
            posthog.capture('experiment viewed', {
                ...getEventPropertiesForExperiment(experiment),
                duration,
            })
        },
        reportExperimentLaunched: ({ experiment, launchDate }) => {
            posthog.capture('experiment launched', {
                ...getEventPropertiesForExperiment(experiment),
                launch_date: launchDate.toISOString(),
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
        reportExperimentCompleted: ({ experiment, endDate, duration, significant }) => {
            posthog.capture('experiment completed', {
                ...getEventPropertiesForExperiment(experiment),
                end_date: endDate.toISOString(),
                duration,
                significant,
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
        reportExperimentVariantShipped: ({ experiment }) => {
            posthog.capture('experiment variant shipped', {
                name: experiment.name,
                id: experiment.id,
                parameters: experiment.parameters,
                secondary_metrics_count: experiment.secondary_metrics.length,
            })
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
        reportExperimentMetricTimeout: ({ experimentId, metric }) => {
            posthog.capture('experiment metric timeout', { experiment_id: experimentId, metric })
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
        reportPropertyGroupFilterAdded: () => {
            posthog.capture('property group filter added')
        },
        reportChangeOuterPropertyGroupFiltersType: ({ type, groupsLength }) => {
            posthog.capture('outer match property groups type changed', { type, groupsLength })
        },
        reportChangeInnerPropertyGroupFiltersType: ({ type, filtersLength }) => {
            posthog.capture('inner match property group filters type changed', { type, filtersLength })
        },
        reportDataManagementDefinitionHovered: ({ type }) => {
            posthog.capture('definition hovered', { type })
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
        reportSurveyCreated: ({ survey, isDuplicate }) => {
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
        reportSurveyTemplateClicked: ({ template }) => {
            posthog.capture('survey template clicked', {
                template,
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
    })),
])
