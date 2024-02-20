import { actions, connect, kea, listeners, path } from 'kea'
import { BarStatus, ResultType } from 'lib/components/CommandBar/types'
import { convertPropertyGroupToProperties, isGroupPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { Dayjs } from 'lib/dayjs'
import { now } from 'lib/dayjs'
import { isCoreFilter, PROPERTY_KEYS } from 'lib/taxonomy'
import posthog from 'posthog-js'
import {
    isFilterWithDisplay,
    isFunnelsFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { EventIndex } from 'scenes/session-recordings/player/eventIndex'
import { SurveyTemplateType } from 'scenes/surveys/constants'
import { userLogic } from 'scenes/userLogic'

import {
    AccessLevel,
    AnyPartialFilterType,
    AnyPropertyFilter,
    DashboardMode,
    DashboardType,
    EntityType,
    Experiment,
    FilterLogicalOperator,
    FilterType,
    FunnelCorrelation,
    HelpType,
    InsightModel,
    InsightShortId,
    InsightType,
    ItemMode,
    PersonType,
    PropertyFilterValue,
    PropertyGroupFilter,
    RecordingReportLoadTimes,
    Resource,
    SessionPlayerData,
    SessionRecordingPlayerTab,
    SessionRecordingUsageType,
    Survey,
} from '~/types'

import type { eventUsageLogicType } from './eventUsageLogicType'

export enum DashboardEventSource {
    LongPress = 'long_press',
    MoreDropdown = 'more_dropdown',
    DashboardHeader = 'dashboard_header',
    Hotkey = 'hotkey',
    InputEnter = 'input_enter',
    Toast = 'toast',
    Browser = 'browser',
    AddDescription = 'add_dashboard_description',
    MainNavigation = 'main_nav',
    DashboardsList = 'dashboards_list',
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

export enum SessionRecordingFilterType {
    Duration = 'duration',
    EventAndAction = 'event_and_action',
    PersonAndCohort = 'person_and_cohort',
    DateRange = 'date_range',
    DurationType = 'duration_type',
}

interface RecordingViewedProps {
    delay: number // Not reported: Number of delayed **seconds** to report event (useful to measure insights where users don't navigate immediately away)
    snapshots_load_time: number // How long it took to load all snapshots
    metadata_load_time: number // How long it took to load all metadata
    events_load_time: number // How long it took to load all events
    performance_events_load_time: number // How long it took to load all performance events
    first_paint_load_time: number // How long it took to first contentful paint (time it takes for user to see first frame)
    duration: number // How long is the total recording (milliseconds)
    recording_id: string // Id of the session
    start_time?: number // Start timestamp of the session
    end_time?: number // End timestamp of the session
    page_change_events_length: number
    recording_width?: number
    loadedFromBlobStorage: boolean

    load_time: number // DEPRECATE: How much time it took to load the session (backend) (milliseconds)
}

function flattenProperties(properties: AnyPropertyFilter[]): string[] {
    const output = []
    for (const prop of properties || []) {
        if (prop.key && isCoreFilter(prop.key)) {
            output.push(prop.key)
        } else {
            output.push('redacted') // Custom property names are not reported
        }
    }
    return output
}

function hasGroupProperties(properties: AnyPropertyFilter[] | PropertyGroupFilter | undefined): boolean {
    const flattenedProperties = convertPropertyGroupToProperties(properties)
    return (
        !!flattenedProperties &&
        flattenedProperties.some(
            (property) => isGroupPropertyFilter(property) && property.group_type_index !== undefined
        )
    )
}

function usedCohortFilterIds(properties: AnyPropertyFilter[] | PropertyGroupFilter | undefined): PropertyFilterValue[] {
    const flattenedProperties = convertPropertyGroupToProperties(properties) || []
    const cohortIds = flattenedProperties
        .filter((p) => p.type === 'cohort')
        .map((p) => p.value)
        .filter((a) => !!a) as number[]

    return cohortIds || []
}

/*
    Takes a full list of filters for an insight and sanitizes any potentially sensitive info to report usage
*/
function sanitizeFilterParams(filters: AnyPartialFilterType): Record<string, any> {
    const { interval, date_from, date_to, filter_test_accounts, insight } = filters

    let properties_local: string[] = []

    // // If we're aggregating this query by groups
    // properties.aggregating_by_groups = filters.aggregation_group_type_index != undefined
    // // If groups are being used in this query
    // properties.using_groups =
    //     hasGroupProperties(filters.properties) || filters.breakdown_group_type_index != undefined

    // let totalEventActionFilters = 0
    // const entities = (filters.events || []).concat(filters.actions || [])
    // entities.forEach((entity) => {
    //     if (entity.properties?.length) {
    //         totalEventActionFilters += entity.properties.length
    //         properties.using_groups = properties.using_groups || hasGroupProperties(entity.properties)
    //     }
    //     if (entity.math_group_type_index != undefined) {
    //         properties.aggregating_by_groups = true
    //     }
    // })
    // properties.using_groups = properties.using_groups || properties.aggregating_by_groups

    const properties = Array.isArray(filters.properties) ? filters.properties : []
    const events = Array.isArray(filters.events) ? filters.events : []
    const actions = Array.isArray(filters.actions) ? filters.actions : []
    const entities = events.concat(actions)

    // If we're aggregating this query by groups
    let aggregating_by_groups = filters.aggregation_group_type_index != undefined
    const breakdown_by_groups = filters.breakdown_group_type_index != undefined
    // If groups are being used in this query
    let using_groups = hasGroupProperties(filters.properties)
    const used_cohort_filter_ids = usedCohortFilterIds(filters.properties)

    for (const entity of entities) {
        const entityProperties = Array.isArray(entity.properties) ? entity.properties : []
        properties_local = properties_local.concat(flattenProperties(entityProperties))

        using_groups = using_groups || hasGroupProperties(entityProperties)
        if (entity.math_group_type_index != undefined) {
            aggregating_by_groups = true
        }
    }
    const properties_global = flattenProperties(properties)

    return {
        display: isFilterWithDisplay(filters) ? filters.display : undefined,
        interval,
        date_from,
        date_to,
        filter_test_accounts,
        formula: isTrendsFilter(filters) ? filters.formula : undefined,
        filters_count: properties?.length || 0,
        events_count: events?.length || 0,
        actions_count: actions?.length || 0,
        funnel_viz_type: isFunnelsFilter(filters) ? filters.funnel_viz_type : undefined,
        funnel_from_step: isFunnelsFilter(filters) ? filters.funnel_from_step : undefined,
        funnel_to_step: isFunnelsFilter(filters) ? filters.funnel_to_step : undefined,
        properties_global,
        properties_global_custom_count: properties_global.filter((item) => item === 'custom').length,
        properties_local,
        properties_local_custom_count: properties_local.filter((item) => item === 'custom').length,
        properties_all: properties_global.concat(properties_local),
        aggregating_by_groups,
        breakdown_by_groups,
        using_groups: using_groups || aggregating_by_groups || breakdown_by_groups,
        used_cohort_filter_ids,
        insight,
    }
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
        reportCohortCreatedFromPersonsModal: (filters: Partial<FilterType>) => ({ filters }),
        // insights
        reportInsightCreated: (insightType: InsightType | null) => ({ insightType }),
        reportInsightSaved: (filters: Partial<FilterType>, isNewInsight: boolean) => ({ filters, isNewInsight }),
        reportInsightViewed: (
            insightModel: Partial<InsightModel>,
            filters: Partial<FilterType>,
            insightMode: ItemMode,
            isFirstLoad: boolean,
            fromDashboard: boolean,
            delay?: number,
            changedFilters?: Record<string, any>,
            isUsingSessionAnalysis?: boolean
        ) => ({
            insightModel,
            filters,
            insightMode,
            isFirstLoad,
            fromDashboard,
            delay,
            changedFilters,
            isUsingSessionAnalysis,
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
        reportCorrelationViewed: (filters: Partial<FilterType>, delay?: number, propertiesTable?: boolean) => ({
            filters,
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
        reportBulkInviteAttempted: (inviteesCount: number, namesCount: number) => ({ inviteesCount, namesCount }),
        reportInviteAttempted: (nameProvided: boolean, instanceEmailAvailable: boolean) => ({
            nameProvided,
            instanceEmailAvailable,
        }),
        reportPersonPropertyUpdated: (
            action: 'added' | 'updated' | 'removed',
            totalProperties: number,
            oldPropertyType?: string,
            newPropertyType?: string
        ) => ({ action, totalProperties, oldPropertyType, newPropertyType }),
        reportDashboardViewed: (dashboard: DashboardType, lastRefreshed: Dayjs | null, delay?: number) => ({
            dashboard,
            delay,
            lastRefreshed,
        }),
        reportDashboardModeToggled: (mode: DashboardMode, source: DashboardEventSource | null) => ({ mode, source }),
        reportDashboardRefreshed: (dashboardId: number, lastRefreshed?: string | Dayjs | null) => ({
            dashboardId,
            lastRefreshed,
        }),
        reportDashboardItemRefreshed: (dashboardItem: InsightModel) => ({ dashboardItem }),
        reportDashboardDateRangeChanged: (dateFrom?: string | Dayjs | null, dateTo?: string | Dayjs | null) => ({
            dateFrom,
            dateTo,
        }),
        reportDashboardPropertiesChanged: true,
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
        reportUpgradeModalShown: (featureName: string) => ({ featureName }),
        reportTimezoneComponentViewed: (
            component: 'label' | 'indicator',
            project_timezone?: string,
            device_timezone?: string | null
        ) => ({ component, project_timezone, device_timezone }),
        reportTestAccountFiltersUpdated: (filters: Record<string, any>[]) => ({ filters }),
        reportPropertySelectOpened: true,
        reportCreatedDashboardFromModal: true,
        reportSavedInsightToDashboard: true,
        reportRemovedInsightFromDashboard: true,
        reportSavedInsightTabChanged: (tab: string) => ({ tab }),
        reportSavedInsightFilterUsed: (filterKeys: string[]) => ({ filterKeys }),
        reportSavedInsightLayoutChanged: (layout: string) => ({ layout }),
        reportSavedInsightNewInsightClicked: (insightType: string) => ({ insightType }),
        reportPersonSplit: (merge_count: number) => ({ merge_count }),
        reportRecording: (
            playerData: SessionPlayerData,
            durations: RecordingReportLoadTimes,
            type: SessionRecordingUsageType,
            delay?: number
        ) => ({ playerData, durations, type, delay }),
        reportHelpButtonViewed: true,
        reportHelpButtonUsed: (help_type: HelpType) => ({ help_type }),
        reportRecordingsListFetched: (loadTime: number) => ({
            loadTime,
        }),
        reportRecordingsListPropertiesFetched: (loadTime: number) => ({ loadTime }),
        reportRecordingsListFilterAdded: (filterType: SessionRecordingFilterType) => ({ filterType }),
        reportRecordingPlayerSeekbarEventHovered: true,
        reportRecordingPlayerSpeedChanged: (newSpeed: number) => ({ newSpeed }),
        reportRecordingPlayerSkipInactivityToggled: (skipInactivity: boolean) => ({ skipInactivity }),
        reportRecordingInspectorTabViewed: (tab: SessionRecordingPlayerTab) => ({ tab }),
        reportRecordingInspectorItemExpanded: (tab: SessionRecordingPlayerTab, index: number) => ({ tab, index }),
        reportRecordingInspectorMiniFilterViewed: (tab: SessionRecordingPlayerTab, minifilterKey: string) => ({
            tab,
            minifilterKey,
        }),
        reportNextRecordingTriggered: (automatic: boolean) => ({
            automatic,
        }),
        reportRecordingExportedToFile: true,
        reportRecordingLoadedFromFile: (data: { success: boolean; error?: string }) => data,
        reportRecordingListVisibilityToggled: (type: string, visible: boolean) => ({ type, visible }),
        reportRecordingPinnedToList: (pinned: boolean) => ({ pinned }),
        reportRecordingPlaylistCreated: (source: 'filters' | 'new' | 'pin' | 'duplicate') => ({ source }),
        reportExperimentArchived: (experiment: Experiment) => ({ experiment }),
        reportExperimentReset: (experiment: Experiment) => ({ experiment }),
        reportExperimentCreated: (experiment: Experiment) => ({ experiment }),
        reportExperimentViewed: (experiment: Experiment) => ({ experiment }),
        reportExperimentLaunched: (experiment: Experiment, launchDate: Dayjs) => ({ experiment, launchDate }),
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
        // Definition Popover
        reportDataManagementDefinitionHovered: (type: TaxonomicFilterGroupType) => ({ type }),
        reportDataManagementDefinitionClickView: (type: TaxonomicFilterGroupType) => ({ type }),
        reportDataManagementDefinitionClickEdit: (type: TaxonomicFilterGroupType) => ({ type }),
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
        reportRecordingOpenedFromRecentRecordingList: true,
        reportPersonOpenedFromNewlySeenPersonsList: true,
        reportIngestionContinueWithoutVerifying: true,
        reportAutocaptureToggled: (autocapture_opt_out: boolean) => ({ autocapture_opt_out }),
        reportAutocaptureExceptionsToggled: (autocapture_opt_in: boolean) => ({ autocapture_opt_in }),
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
        reportActivationSideBarShown: (
            activeTasksCount: number,
            completedTasksCount: number,
            completionPercent: number
        ) => ({ activeTasksCount, completedTasksCount, completionPercent }),
        reportActivationSideBarTaskClicked: (key: string) => ({ key }),
        reportBillingUpgradeClicked: (plan: string) => ({ plan }),
        reportRoleCreated: (role: string) => ({ role }),
        reportResourceAccessLevelUpdated: (resourceType: Resource, roleName: string, accessLevel: AccessLevel) => ({
            resourceType,
            roleName,
            accessLevel,
        }),
        reportRoleCustomAddedToAResource: (resourceType: Resource, rolesLength: number) => ({
            resourceType,
            rolesLength,
        }),
        reportFlagsCodeExampleInteraction: (optionType: string) => ({
            optionType,
        }),
        reportFlagsCodeExampleLanguage: (language: string) => ({
            language,
        }),
        reportSurveyViewed: (survey: Survey) => ({
            survey,
        }),
        reportSurveyCreated: (survey: Survey) => ({ survey }),
        reportSurveyEdited: (survey: Survey) => ({ survey }),
        reportSurveyLaunched: (survey: Survey) => ({ survey }),
        reportSurveyStopped: (survey: Survey) => ({ survey }),
        reportSurveyResumed: (survey: Survey) => ({ survey }),
        reportSurveyArchived: (survey: Survey) => ({ survey }),
        reportSurveyTemplateClicked: (template: SurveyTemplateType) => ({ template }),
        reportProductUnsubscribed: (product: string) => ({ product }),
        // onboarding
        reportOnboardingProductSelected: (
            productKey: string,
            includeFirstOnboardingProductOnUserProperties: boolean
        ) => ({
            productKey,
            includeFirstOnboardingProductOnUserProperties,
        }),
        reportOnboardingCompleted: (productKey: string) => ({ productKey }),
        reportSubscribedDuringOnboarding: (productKey: string) => ({ productKey }),
        // command bar
        reportCommandBarStatusChanged: (status: BarStatus) => ({ status }),
        reportCommandBarSearch: (queryLength: number) => ({ queryLength }),
        reportCommandBarSearchResultOpened: (type: ResultType) => ({ type }),
        reportCommandBarActionSearch: (query: string) => ({ query }),
        reportCommandBarActionResultExecuted: (resultDisplay) => ({ resultDisplay }),
    }),
    listeners(({ values }) => ({
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
        reportInsightCreated: async ({ insightType }, breakpoint) => {
            // "insight created" essentially means that the user clicked "New insight"
            await breakpoint(500) // Debounce to avoid multiple quick "New insight" clicks being reported
            posthog.capture('insight created', { insight: insightType })
        },
        reportInsightSaved: async ({ filters, isNewInsight }) => {
            // "insight saved" is a proxy for the new insight's results being valuable to the user
            posthog.capture('insight saved', {
                ...filters,
                is_new_insight: isNewInsight,
            })
        },
        reportInsightViewed: ({
            insightModel,
            filters,
            insightMode,
            isFirstLoad,
            fromDashboard,
            delay,
            changedFilters,
            isUsingSessionAnalysis,
        }) => {
            const properties: Record<string, any> = {
                ...sanitizeFilterParams(filters),
                report_delay: delay,
                is_first_component_load: isFirstLoad,
                from_dashboard: fromDashboard,
            }

            properties.total_event_actions_count = (properties.events_count || 0) + (properties.actions_count || 0)

            let totalEventActionFilters = 0
            const entities = (filters.events || []).concat(filters.actions || [])
            entities.forEach((entity) => {
                if (entity.properties?.length) {
                    totalEventActionFilters += entity.properties.length
                }
            })

            // The total # of filters applied on events and actions.
            properties.total_event_action_filters_count = totalEventActionFilters

            // Custom properties for each insight
            if (isTrendsFilter(filters)) {
                properties.breakdown_type = filters.breakdown_type
                properties.breakdown = filters.breakdown
                properties.using_session_analysis = isUsingSessionAnalysis
                properties.compare = filters.compare // "Compare previous" option
                properties.show_legend = filters.show_legend
            } else if (isRetentionFilter(filters)) {
                properties.period = filters.period
                properties.date_to = filters.date_to
                properties.retention_type = filters.retention_type
                const cohortizingEvent = filters.target_entity
                const retainingEvent = filters.returning_entity
                properties.same_retention_and_cohortizing_event =
                    cohortizingEvent?.id == retainingEvent?.id && cohortizingEvent?.type == retainingEvent?.type
            } else if (isPathsFilter(filters)) {
                properties.path_type = filters.path_type
                properties.has_start_point = !!filters.start_point
                properties.has_end_point = !!filters.end_point
                properties.has_funnel_filter = Object.keys(filters.funnel_filter || {}).length > 0
                properties.funnel_paths = filters.funnel_paths
                properties.has_min_edge_weight = !!filters.min_edge_weight
                properties.has_max_edge_weight = !!filters.max_edge_weight
                properties.has_edge_limit = !!filters.edge_limit
                properties.has_local_cleaning_filters = (filters.local_path_cleaning_filters || []).length > 0
                properties.has_path_replacements = !!filters.path_replacements
                properties.has_wildcards = (filters.path_groupings || []).length > 0
                properties.using_advanced_features =
                    properties.has_min_edge_weight ||
                    properties.has_max_edge_weight ||
                    properties.has_edge_limit ||
                    properties.has_local_cleaning_filters ||
                    properties.has_path_replacements
                properties.using_basic_features =
                    properties.has_start_point ||
                    properties.has_end_point ||
                    properties.has_funnel_filter ||
                    properties.has_wildcards
            } else if (isStickinessFilter(filters)) {
                properties.stickiness_days = filters.stickiness_days
            }
            properties.mode = insightMode // View or edit
            properties.viewer_is_creator =
                insightModel.created_by?.uuid && values.user?.uuid
                    ? insightModel.created_by?.uuid === values.user?.uuid
                    : null
            properties.is_saved = insightModel.saved
            properties.description_length = insightModel.description?.length ?? 0
            properties.tags_count = insightModel.tags?.length ?? 0

            const eventName = delay ? 'insight analyzed' : 'insight viewed'
            posthog.capture(eventName, { ...properties, ...(changedFilters ? changedFilters : {}) })
        },
        reportPersonsModalViewed: async ({ params }) => {
            posthog.capture('insight person modal viewed', params)
        },
        reportCohortCreatedFromPersonsModal: async ({ filters }) => {
            posthog.capture('person modal cohort created', sanitizeFilterParams(filters))
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
                sample_items_count: 0,
                item_count: dashboard.tiles?.length || 0,
                created_by_system: !dashboard.created_by,
                dashboard_id: id,
                lastRefreshed: lastRefreshed?.toISOString(),
                refreshAge: lastRefreshed ? now().diff(lastRefreshed, 'seconds') : undefined,
            }

            for (const item of dashboard.tiles || []) {
                if (item.insight) {
                    const key = `${item.insight.filters?.insight?.toLowerCase() || InsightType.TRENDS}_count`
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
        reportBulkInviteAttempted: async ({
            inviteesCount,
            namesCount,
        }: {
            inviteesCount: number
            namesCount: number
        }) => {
            // namesCount -> Number of invitees for which a name was provided
            posthog.capture('bulk invite attempted', { invitees_count: inviteesCount, name_count: namesCount })
            for (let i = 0; i < inviteesCount; i++) {
                posthog.capture('team member invited')
            }
        },
        reportInviteAttempted: async ({ nameProvided, instanceEmailAvailable }) => {
            posthog.capture('team member invited')
            posthog.capture('team invite attempted', {
                name_provided: nameProvided,
                instance_email_available: instanceEmailAvailable,
            })
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
        reportPersonPropertyUpdated: async ({ action, totalProperties, oldPropertyType, newPropertyType }) => {
            posthog.capture(`person property ${action}`, {
                old_property_type: oldPropertyType !== 'undefined' ? oldPropertyType : undefined,
                new_property_type: newPropertyType !== 'undefined' ? newPropertyType : undefined,
                total_properties: totalProperties,
            })
        },
        reportDashboardModeToggled: async ({ mode, source }) => {
            posthog.capture('dashboard mode toggled', { mode, source })
        },
        reportDashboardRefreshed: async ({ dashboardId, lastRefreshed }) => {
            posthog.capture(`dashboard refreshed`, {
                dashboard_id: dashboardId,
                last_refreshed: lastRefreshed?.toString(),
                refreshAge: lastRefreshed ? now().diff(lastRefreshed, 'seconds') : undefined,
            })
        },
        reportDashboardDateRangeChanged: async ({ dateFrom, dateTo }) => {
            posthog.capture(`dashboard date range changed`, {
                date_from: dateFrom?.toString() || 'Custom',
                date_to: dateTo?.toString(),
            })
        },
        reportDashboardPropertiesChanged: async () => {
            posthog.capture(`dashboard properties changed`)
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

        reportInsightFilterRemoved: async ({ index }) => {
            posthog.capture('local filter removed', { index })
        },
        reportInsightFilterAdded: async ({ newLength }) => {
            posthog.capture('filter added', { newLength })
        },
        reportInsightFilterSet: async ({ filters }) => {
            posthog.capture('filters set', { filters })
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
        reportSavedInsightToDashboard: async () => {
            posthog.capture('saved insight to dashboard')
        },
        reportRemovedInsightFromDashboard: async () => {
            posthog.capture('removed insight from dashboard')
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
        reportRecording: ({ playerData, durations, type }) => {
            // @ts-expect-error
            const eventIndex = new EventIndex(playerData?.snapshots || [])
            const payload: Partial<RecordingViewedProps> = {
                snapshots_load_time: durations.snapshots,
                metadata_load_time: durations.metadata,
                events_load_time: durations.events,
                first_paint_load_time: durations.firstPaint,
                duration: eventIndex.getDuration(),
                recording_id: playerData.sessionRecordingId,
                start_time: playerData.start?.valueOf() ?? 0,
                end_time: playerData.end?.valueOf() ?? 0,
                page_change_events_length: eventIndex.pageChangeEvents().length,
                recording_width: eventIndex.getRecordingScreenMetadata(0)[0]?.width,
                load_time: durations.firstPaint ?? 0, // TODO: DEPRECATED field. Keep around so dashboards don't break
            }
            posthog.capture(`recording ${type}`, payload)
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
        reportCorrelationViewed: ({ delay, filters, propertiesTable }) => {
            if (delay === 0) {
                posthog.capture(`correlation${propertiesTable ? ' properties' : ''} viewed`, { filters })
            } else {
                posthog.capture(`correlation${propertiesTable ? ' properties' : ''} analyzed`, {
                    filters,
                    delay,
                })
            }
        },
        reportRecordingsListFilterAdded: ({ filterType }) => {
            posthog.capture('recording list filter added', { filter_type: filterType })
        },
        reportRecordingsListFetched: ({ loadTime }) => {
            posthog.capture('recording list fetched', { load_time: loadTime, listing_version: '3' })
        },
        reportRecordingsListPropertiesFetched: ({ loadTime }) => {
            posthog.capture('recording list properties fetched', { load_time: loadTime })
        },
        reportRecordingPlayerSeekbarEventHovered: () => {
            posthog.capture('recording player seekbar event hovered')
        },
        reportRecordingPlayerSpeedChanged: ({ newSpeed }) => {
            posthog.capture('recording player speed changed', { new_speed: newSpeed })
        },
        reportRecordingPlayerSkipInactivityToggled: ({ skipInactivity }) => {
            posthog.capture('recording player skip inactivity toggled', { skip_inactivity: skipInactivity })
        },
        reportRecordingInspectorTabViewed: ({ tab }) => {
            posthog.capture('recording inspector tab viewed', { tab })
        },
        reportRecordingInspectorItemExpanded: ({ tab, index }) => {
            posthog.capture('recording inspector item expanded', { tab, index })
        },
        reportRecordingInspectorMiniFilterViewed: ({ tab, minifilterKey }) => {
            posthog.capture('recording inspector minifilter selected', { tab, minifilterKey })
        },
        reportNextRecordingTriggered: ({ automatic }) => {
            posthog.capture('recording next recording triggered', { automatic })
        },
        reportRecordingExportedToFile: () => {
            posthog.capture('recording exported to file')
        },
        reportRecordingLoadedFromFile: (properties) => {
            posthog.capture('recording loaded from file', properties)
        },
        reportRecordingListVisibilityToggled: (properties) => {
            posthog.capture('recording list visibility toggled', properties)
        },
        reportRecordingPinnedToList: (properties) => {
            posthog.capture('recording pinned to list', properties)
        },
        reportRecordingPlaylistCreated: (properties) => {
            posthog.capture('recording playlist created', properties)
        },
        reportExperimentArchived: ({ experiment }) => {
            posthog.capture('experiment archived', {
                name: experiment.name,
                id: experiment.id,
                filters: sanitizeFilterParams(experiment.filters),
                parameters: experiment.parameters,
            })
        },
        reportExperimentReset: ({ experiment }) => {
            posthog.capture('experiment reset', {
                name: experiment.name,
                id: experiment.id,
                filters: sanitizeFilterParams(experiment.filters),
                parameters: experiment.parameters,
            })
        },
        reportExperimentCreated: ({ experiment }) => {
            posthog.capture('experiment created', {
                name: experiment.name,
                id: experiment.id,
                filters: sanitizeFilterParams(experiment.filters),
                parameters: experiment.parameters,
                secondary_metrics_count: experiment.secondary_metrics.length,
            })
        },
        reportExperimentViewed: ({ experiment }) => {
            posthog.capture('experiment viewed', {
                name: experiment.name,
                id: experiment.id,
                filters: sanitizeFilterParams(experiment.filters),
                parameters: experiment.parameters,
                secondary_metrics_count: experiment.secondary_metrics.length,
            })
        },
        reportExperimentLaunched: ({ experiment, launchDate }) => {
            posthog.capture('experiment launched', {
                name: experiment.name,
                id: experiment.id,
                filters: sanitizeFilterParams(experiment.filters),
                parameters: experiment.parameters,
                secondary_metrics_count: experiment.secondary_metrics.length,
                launch_date: launchDate.toISOString(),
            })
        },
        reportExperimentCompleted: ({ experiment, endDate, duration, significant }) => {
            posthog.capture('experiment completed', {
                name: experiment.name,
                id: experiment.id,
                filters: sanitizeFilterParams(experiment.filters),
                parameters: experiment.parameters,
                secondary_metrics_count: experiment.secondary_metrics.length,
                end_date: endDate.toISOString(),
                duration,
                significant,
            })
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
        reportRecordingOpenedFromRecentRecordingList: () => {
            posthog.capture('recording opened from recent recording list')
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
        reportActivationSideBarShown: ({ activeTasksCount, completedTasksCount, completionPercent }) => {
            posthog.capture('activation sidebar shown', {
                active_tasks_count: activeTasksCount,
                completed_tasks_count: completedTasksCount,
                completion_percent_count: completionPercent,
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
        reportSurveyCreated: ({ survey }) => {
            posthog.capture('survey created', {
                name: survey.name,
                id: survey.id,
                survey_type: survey.type,
                questions_length: survey.questions.length,
                question_types: survey.questions.map((question) => question.type),
            })
        },
        reportSurveyLaunched: ({ survey }) => {
            posthog.capture('survey launched', {
                name: survey.name,
                id: survey.id,
                survey_type: survey.type,
                question_types: survey.questions.map((question) => question.type),
                created_at: survey.created_at,
                start_date: survey.start_date,
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
        reportSurveyStopped: ({ survey }) => {
            posthog.capture('survey stopped', {
                name: survey.name,
                id: survey.id,
                created_at: survey.created_at,
                start_date: survey.start_date,
                end_date: survey.end_date,
            })
        },
        reportSurveyResumed: ({ survey }) => {
            posthog.capture('survey resumed', {
                name: survey.name,
                id: survey.id,
                created_at: survey.created_at,
                start_date: survey.start_date,
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
            posthog.capture('survey edited', {
                name: survey.name,
                id: survey.id,
                created_at: survey.created_at,
                start_date: survey.start_date,
            })
        },
        reportSurveyTemplateClicked: ({ template }) => {
            posthog.capture('survey template clicked', {
                template,
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
        reportOnboardingProductSelected: ({ productKey, includeFirstOnboardingProductOnUserProperties }) => {
            posthog.capture('onboarding product selected', {
                product_key: productKey,
                $set_once: {
                    first_onboarding_product_selected: includeFirstOnboardingProductOnUserProperties
                        ? productKey
                        : undefined,
                },
            })
        },
        reportOnboardingCompleted: ({ productKey }) => {
            posthog.capture('onboarding completed', {
                product_key: productKey,
            })
        },
        reportSubscribedDuringOnboarding: ({ productKey }) => {
            posthog.capture('subscribed during onboarding', {
                product_key: productKey,
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
    })),
])
