import { kea } from 'kea'
import { isPostHogProp, keyMappingKeys } from 'lib/components/PropertyKeyInfo'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'
import type { eventUsageLogicType } from './eventUsageLogicType'
import {
    AnnotationType,
    FilterType,
    DashboardType,
    PersonType,
    DashboardMode,
    EntityType,
    InsightModel,
    InsightType,
    HelpType,
    SessionPlayerData,
    AvailableFeature,
    SessionRecordingUsageType,
    FunnelCorrelation,
    ItemMode,
    AnyPropertyFilter,
    Experiment,
    PropertyGroupFilter,
    FilterLogicalOperator,
    PropertyFilterValue,
} from '~/types'
import type { Dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import type { PersonsModalParams } from 'scenes/trends/personsModalLogic'
import { EventIndex } from '@posthog/react-rrweb-player'
import { convertPropertyGroupToProperties } from 'lib/utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PlatformType, Framework } from 'scenes/ingestion/types'
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

export enum RecordingWatchedSource {
    Direct = 'direct', // Visiting the URL directly
    Unknown = 'unknown',
    RecordingsList = 'recordings_list',
    ProjectHomepage = 'project_homepage',
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
}

interface RecordingViewedProps {
    delay: number // Not reported: Number of delayed **seconds** to report event (useful to measure insights where users don't navigate immediately away)
    load_time: number // How much time it took to load the session (backend) (milliseconds)
    duration: number // How long is the total recording (milliseconds)
    start_time?: number // Start timestamp of the session
    end_time?: number // End timestamp of the session
    page_change_events_length: number
    recording_width?: number
    source: RecordingWatchedSource
}

function flattenProperties(properties: AnyPropertyFilter[]): string[] {
    const output = []
    for (const prop of properties || []) {
        if (prop.key && isPostHogProp(prop.key)) {
            output.push(prop.key)
        } else {
            output.push('redacted') // Custom property names are not reported
        }
    }
    return output
}

function hasGroupProperties(properties: AnyPropertyFilter[] | PropertyGroupFilter | undefined): boolean {
    const flattenedProperties = convertPropertyGroupToProperties(properties)
    return !!flattenedProperties && flattenedProperties.some((property) => property.group_type_index != undefined)
}

function usedCohortFilterIds(properties: AnyPropertyFilter[] | PropertyGroupFilter | undefined): PropertyFilterValue[] {
    const flattenedProperties = convertPropertyGroupToProperties(properties)
    const cohortIds = flattenedProperties?.filter((p) => p.type === 'cohort').map((p) => p.value)

    return cohortIds || []
}

/*
    Takes a full list of filters for an insight and sanitizes any potentially sensitive info to report usage
*/
function sanitizeFilterParams(filters: Partial<FilterType>): Record<string, any> {
    const {
        display,
        interval,
        date_from,
        date_to,
        filter_test_accounts,
        formula,
        funnel_viz_type,
        funnel_from_step,
        funnel_to_step,
    } = filters

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
        properties_local = properties_local.concat(flattenProperties(entity.properties || []))

        using_groups = using_groups || hasGroupProperties(entity.properties || [])
        if (entity.math_group_type_index != undefined) {
            aggregating_by_groups = true
        }
    }
    const properties_global = flattenProperties(properties)

    return {
        display,
        interval,
        date_from,
        date_to,
        filter_test_accounts,
        formula,
        filters_count: properties?.length || 0,
        events_count: events?.length || 0,
        actions_count: actions?.length || 0,
        funnel_viz_type,
        funnel_from_step,
        funnel_to_step,
        properties_global,
        properties_global_custom_count: properties_global.filter((item) => item === 'custom').length,
        properties_local,
        properties_local_custom_count: properties_local.filter((item) => item === 'custom').length,
        properties_all: properties_global.concat(properties_local),
        aggregating_by_groups,
        breakdown_by_groups,
        using_groups: using_groups || aggregating_by_groups || breakdown_by_groups,
        used_cohort_filter_ids,
    }
}

export const eventUsageLogic = kea<eventUsageLogicType>({
    path: ['lib', 'utils', 'eventUsageLogic'],
    connect: {
        values: [preflightLogic, ['realm'], userLogic, ['user']],
    },
    actions: {
        reportAnnotationViewed: (annotations: AnnotationType[] | null) => ({ annotations }),
        reportPersonDetailViewed: (person: PersonType) => ({ person }),
        reportInsightCreated: (insight: InsightType | null) => ({ insight }),
        reportInsightViewed: (
            insightModel: Partial<InsightModel>,
            filters: Partial<FilterType>,
            insightMode: ItemMode,
            isFirstLoad: boolean,
            fromDashboard: boolean,
            delay?: number,
            changedFilters?: Record<string, any>
        ) => ({
            insightModel,
            filters,
            insightMode,
            isFirstLoad,
            fromDashboard,
            delay,
            changedFilters,
        }),
        reportPersonsModalViewed: (params: PersonsModalParams, count: number, hasNext: boolean) => ({
            params,
            count,
            hasNext,
        }),
        reportCohortCreatedFromPersonsModal: (filters: Partial<FilterType>) => ({ filters }),
        reportBookmarkletDragged: true,
        reportIngestionBookmarkletCollapsible: (activePanels: string[]) => ({ activePanels }),
        reportProjectCreationSubmitted: (projectCount: number, nameLength: number) => ({ projectCount, nameLength }),
        reportDemoWarningDismissed: (key: string) => ({ key }),
        reportOnboardingStepTriggered: (stepKey: string, extraArgs: Record<string, string | number | boolean>) => ({
            stepKey,
            extraArgs,
        }),
        reportBulkInviteAttempted: (inviteesCount: number, namesCount: number) => ({ inviteesCount, namesCount }),
        reportInviteAttempted: (nameProvided: boolean, instanceEmailAvailable: boolean) => ({
            nameProvided,
            instanceEmailAvailable,
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
        reportFunnelStepReordered: true,
        reportPersonPropertyUpdated: (
            action: 'added' | 'updated' | 'removed',
            totalProperties: number,
            oldPropertyType?: string,
            newPropertyType?: string
        ) => ({ action, totalProperties, oldPropertyType, newPropertyType }),
        reportDashboardViewed: (dashboard: DashboardType, hasShareToken: boolean, delay?: number) => ({
            dashboard,
            hasShareToken,
            delay,
        }),
        reportDashboardModeToggled: (mode: DashboardMode, source: DashboardEventSource | null) => ({ mode, source }),
        reportDashboardRefreshed: (lastRefreshed?: string | Dayjs | null) => ({ lastRefreshed }),
        reportDashboardItemRefreshed: (dashboardItem: InsightModel) => ({ dashboardItem }),
        reportDashboardDateRangeChanged: (dateFrom?: string | Dayjs, dateTo?: string | Dayjs | null) => ({
            dateFrom,
            dateTo,
        }),
        reportDashboardPropertiesChanged: true,
        reportDashboardPinToggled: (pinned: boolean, source: DashboardEventSource) => ({
            pinned,
            source,
        }),
        reportDashboardDropdownNavigation: true,
        reportDashboardFrontEndUpdate: (
            attribute: 'name' | 'description' | 'tags',
            originalLength: number,
            newLength: number
        ) => ({ attribute, originalLength, newLength }),
        reportDashboardShareToggled: (isShared: boolean) => ({ isShared }),
        reportUpgradeModalShown: (featureName: string) => ({ featureName }),
        reportIngestionLandingSeen: true,
        reportTimezoneComponentViewed: (
            component: 'label' | 'indicator',
            project_timezone?: string,
            device_timezone?: string | null
        ) => ({ component, project_timezone, device_timezone }),
        reportTestAccountFiltersUpdated: (filters: Record<string, any>[]) => ({ filters }),
        reportProjectHomeItemClicked: (
            module: string,
            item: string,
            extraProps?: Record<string, string | boolean | number | undefined>
        ) => ({ module, item, extraProps }),
        reportProjectHomeSeen: (teamHasData: boolean) => ({ teamHasData }),
        reportInsightHistoryItemClicked: (itemType: string, displayLocation?: string) => ({
            itemType,
            displayLocation,
        }),
        reportEventSearched: (searchTerm: string, extraProps?: Record<string, number>) => ({
            searchTerm,
            extraProps,
        }),
        reportInsightFilterUpdated: (index: number, name: string | null, type?: EntityType) => ({ type, index, name }),
        reportInsightFilterRemoved: (index: number) => ({ index }),
        reportInsightFilterAdded: (newLength: number, source: GraphSeriesAddedSource) => ({ newLength, source }),
        reportInsightFilterSet: (
            filters: Array<{
                id: string | number | null
                type?: EntityType
            }>
        ) => ({ filters }),
        reportEntityFilterVisibilitySet: (index: number, visible: boolean) => ({ index, visible }),
        reportPropertySelectOpened: true,
        reportCreatedDashboardFromModal: true,
        reportSavedInsightToDashboard: true,
        reportRemovedInsightFromDashboard: true,
        reportInsightsTabReset: true,
        reportInsightsTableCalcToggled: (mode: string) => ({ mode }),
        reportInsightShortUrlVisited: (valid: boolean, insight: InsightType | null) => ({ valid, insight }),
        reportSavedInsightTabChanged: (tab: string) => ({ tab }),
        reportSavedInsightFilterUsed: (filterKeys: string[]) => ({ filterKeys }),
        reportSavedInsightLayoutChanged: (layout: string) => ({ layout }),
        reportSavedInsightNewInsightClicked: (insightType: string) => ({ insightType }),
        reportPayGateShown: (identifier: AvailableFeature) => ({ identifier }),
        reportPayGateDismissed: (identifier: AvailableFeature) => ({ identifier }),
        reportPersonMerged: (merge_count: number) => ({ merge_count }),
        reportPersonSplit: (merge_count: number) => ({ merge_count }),
        reportRecording: (
            recordingData: SessionPlayerData,
            source: RecordingWatchedSource,
            loadTime: number,
            type: SessionRecordingUsageType,
            delay?: number
        ) => ({ recordingData, source, loadTime, type, delay }),
        reportRecordingScrollTo: (rowIndex: number) => ({ rowIndex }),
        reportHelpButtonViewed: true,
        reportHelpButtonUsed: (help_type: HelpType) => ({ help_type }),
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
        reportRecordingEventsFetched: (numEvents: number, loadTime: number) => ({ numEvents, loadTime }),
        reportCorrelationAnalysisFeedback: (rating: number) => ({ rating }),
        reportCorrelationAnalysisDetailedFeedback: (rating: number, comments: string) => ({ rating, comments }),
        reportRecordingsListFetched: (loadTime: number) => ({ loadTime }),
        reportRecordingsListFilterAdded: (filterType: SessionRecordingFilterType) => ({ filterType }),
        reportRecordingPlayerSeekbarEventHovered: true,
        reportRecordingPlayerSpeedChanged: (newSpeed: number) => ({ newSpeed }),
        reportRecordingPlayerSkipInactivityToggled: (skipInactivity: boolean) => ({ skipInactivity }),
        reportRecordingConsoleFeedback: (logCount: number, response: string, question: string) => ({
            logCount,
            response,
            question,
        }),
        reportRecordingConsoleViewed: (logCount: number) => ({ logCount }),
        reportExperimentArchived: (experiment: Experiment) => ({ experiment }),
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
        reportPropertyGroupFilterAdded: true,
        reportChangeOuterPropertyGroupFiltersType: (type: FilterLogicalOperator, groupsLength: number) => ({
            type,
            groupsLength,
        }),
        reportChangeInnerPropertyGroupFiltersType: (type: FilterLogicalOperator, filtersLength: number) => ({
            type,
            filtersLength,
        }),
        reportPrimaryDashboardModalOpened: true,
        reportPrimaryDashboardChanged: true,
        // Definition Popup
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
        reportDataManagementEventDefinitionsPageClickNestedPropertyDetail: true,
        reportDataManagementEventPropertyDefinitionsPageLoadSucceeded: (loadTime: number, resultsLength: number) => ({
            loadTime,
            resultsLength,
        }),
        reportDataManagementEventPropertyDefinitionsPageLoadFailed: (loadTime: number, error: string) => ({
            loadTime,
            error,
        }),
        reportInsightOpenedFromRecentInsightList: true,
        reportRecordingOpenedFromRecentRecordingList: true,
        reportPersonOpenedFromNewlySeenPersonsList: true,
        reportTeamHasIngestedEvents: true,
        reportIngestionSelectPlatformType: (platform: PlatformType) => ({ platform }),
        reportIngestionSelectFrameworkType: (framework: Framework) => ({ framework }),
        reportIngestionHelpClicked: (type: string) => ({ type }),
        reportIngestionTryWithBookmarkletClicked: true,
        reportIngestionContinueWithoutVerifying: true,
        reportIngestionThirdPartyAboutClicked: (name: string) => ({ name }),
        reportIngestionThirdPartyConfigureClicked: (name: string) => ({ name }),
        reportIngestionThirdPartyPluginInstalled: (name: string) => ({ name }),
        reportFailedToCreateFeatureFlagWithCohort: (code: string, detail: string) => ({ code, detail }),
        reportInviteMembersButtonClicked: true,
        reportIngestionSidebarButtonClicked: (name: string) => ({ name }),
    },
    listeners: ({ values }) => ({
        reportAnnotationViewed: async ({ annotations }, breakpoint) => {
            if (!annotations) {
                // If value is `null` the component has been unmounted, don't report
                return
            }

            await breakpoint(500) // Debounce calls to make sure we don't report accidentally hovering over an annotation.

            for (const annotation of annotations) {
                /* Report one event per annotation */
                const properties = {
                    total_items_count: annotations.length,
                    content_length: annotation.content.length,
                    scope: annotation.scope,
                    deleted: annotation.deleted,
                    created_by_me: annotation.created_by && annotation.created_by?.uuid === userLogic.values.user?.uuid,
                    creation_type: annotation.creation_type,
                    created_at: annotation.created_at,
                    updated_at: annotation.updated_at,
                }
                posthog.capture('annotation viewed', properties)
            }
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
                if (keyMappingKeys.includes(prop)) {
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
        reportInsightCreated: async ({ insight }, breakpoint) => {
            await breakpoint(500) // Debounce to avoid multiple quick "New insight" clicks being reported
            posthog.capture('insight created', { insight })
        },
        reportInsightViewed: ({
            insightModel,
            filters,
            insightMode,
            isFirstLoad,
            fromDashboard,
            delay,
            changedFilters,
        }) => {
            const { insight } = filters

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
            if (insight === 'TRENDS') {
                properties.breakdown_type = filters.breakdown_type
                properties.breakdown = filters.breakdown
            } else if (insight === 'RETENTION') {
                properties.period = filters.period
                properties.date_to = filters.date_to
                properties.retention_type = filters.retention_type
                const cohortizingEvent = filters.target_entity
                const retainingEvent = filters.returning_entity
                properties.same_retention_and_cohortizing_event =
                    cohortizingEvent?.id == retainingEvent?.id && cohortizingEvent?.type == retainingEvent?.type
            } else if (insight === 'PATHS') {
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
            } else if (insight === 'STICKINESS') {
                properties.stickiness_days = filters.stickiness_days
            }
            properties.compare = filters.compare // "Compare previous" option
            properties.mode = insightMode // View or edit

            properties.viewer_is_creator = insightModel.created_by?.uuid === values.user?.uuid ?? null // `null` means we couldn't determine this
            properties.is_saved = insightModel.saved
            properties.description_length = insightModel.description?.length ?? 0
            properties.tags_count = insightModel.tags?.length ?? 0

            const eventName = delay ? 'insight analyzed' : 'insight viewed'
            posthog.capture(eventName, { ...properties, ...(changedFilters ? changedFilters : {}) })
        },
        reportPersonsModalViewed: async ({ params, count, hasNext }) => {
            const { funnelStep, filters, breakdown_value, saveOriginal, searchTerm, date_from, date_to } = params
            const properties = {
                ...sanitizeFilterParams(filters),
                date_from,
                date_to,
                funnel_step: funnelStep,
                has_breakdown_value: Boolean(breakdown_value),
                save_original: saveOriginal,
                has_search_term: Boolean(searchTerm),
                count,
                has_next: hasNext,
            }
            posthog.capture('insight person modal viewed', properties)
        },
        reportCohortCreatedFromPersonsModal: async ({ filters }) => {
            posthog.capture('person modal cohort created', sanitizeFilterParams(filters))
        },
        reportDashboardViewed: async ({ dashboard, hasShareToken, delay }, breakpoint) => {
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
                item_count: dashboard.items?.length || 0,
                created_by_system: !dashboard.created_by,
                has_share_token: hasShareToken,
                dashboard_id: id,
            }

            for (const item of dashboard.items || []) {
                const key = `${item.filters?.insight?.toLowerCase() || InsightType.TRENDS}_count`
                if (!properties[key]) {
                    properties[key] = 1
                } else {
                    properties[key] += 1
                }
                properties.sample_items_count += item.is_sample ? 1 : 0
            }

            const eventName = delay ? 'dashboard analyzed' : 'viewed dashboard' // `viewed dashboard` name is kept for backwards compatibility
            posthog.capture(eventName, properties)
        },
        reportBookmarkletDragged: async (_, breakpoint) => {
            await breakpoint(500)
            posthog.capture('bookmarklet drag start')
        },
        reportIngestionBookmarkletCollapsible: async ({ activePanels }, breakpoint) => {
            breakpoint(500)
            const action = activePanels.includes('bookmarklet') ? 'shown' : 'hidden'
            posthog.capture(`ingestion bookmarklet panel ${action}`)
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
        reportDemoWarningDismissed: async ({ key }) => {
            posthog.capture('demo warning dismissed', { warning_key: key })
        },
        reportOnboardingStepTriggered: async ({ stepKey, extraArgs }) => {
            // Fired after the user attempts to start an onboarding step (e.g. clicking on create project)
            posthog.capture('onboarding step triggered', { step: stepKey, ...extraArgs })
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
        },
        reportInviteAttempted: async ({ nameProvided, instanceEmailAvailable }) => {
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
        reportDashboardRefreshed: async ({ lastRefreshed }) => {
            posthog.capture(`dashboard refreshed`, { last_refreshed: lastRefreshed?.toString() })
        },
        reportDashboardDateRangeChanged: async ({ dateFrom, dateTo }) => {
            posthog.capture(`dashboard date range changed`, {
                date_from: dateFrom?.toString(),
                date_to: dateTo?.toString(),
            })
        },
        reportDashboardPropertiesChanged: async () => {
            posthog.capture(`dashboard properties changed`)
        },
        reportDashboardPinToggled: async (payload) => {
            posthog.capture(`dashboard pin toggled`, payload)
        },
        reportDashboardDropdownNavigation: async () => {
            /* Triggered when a user navigates using the dropdown in the header.
             */
            posthog.capture(`dashboard dropdown navigated`)
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
        reportIngestionLandingSeen: async () => {
            posthog.capture('ingestion landing seen')
        },
        reportProjectHomeItemClicked: async ({ module, item, extraProps }) => {
            const defaultProps = { module, item }
            const eventProps = extraProps ? { ...defaultProps, ...extraProps } : defaultProps
            posthog.capture('project home item clicked', eventProps)
        },
        reportProjectHomeSeen: async ({ teamHasData }) => {
            posthog.capture('project home seen', { team_has_data: teamHasData })
        },

        reportInsightHistoryItemClicked: async ({ itemType, displayLocation }) => {
            posthog.capture('insight history item clicked', { item_type: itemType, display_location: displayLocation })
            if (displayLocation === 'project home') {
                // Special case to help w/ project home reporting.
                posthog.capture('project home item clicked', {
                    module: 'insights',
                    item: 'recent_analysis',
                    item_type: itemType,
                    display_location: displayLocation,
                })
            }
        },

        reportEventSearched: async ({ searchTerm, extraProps }) => {
            // This event is only captured on PostHog Cloud
            if (values.realm === 'cloud') {
                // Triggered when a search is executed for an action/event (mainly for use on insights)
                posthog.capture('event searched', { searchTerm, ...extraProps })
            }
        },
        reportInsightFilterUpdated: async ({ type, index, name }) => {
            posthog.capture('filter updated', { type, index, name })
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
        reportInsightsTabReset: async () => {
            posthog.capture('insights tab reset')
        },
        reportInsightsTableCalcToggled: async (payload) => {
            posthog.capture('insights table calc toggled', payload)
        },
        reportInsightShortUrlVisited: (props) => {
            posthog.capture('insight short url visited', props)
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
        reportRecording: ({ recordingData, source, loadTime, type }) => {
            // @ts-expect-error
            const eventIndex = new EventIndex(recordingData?.snapshots || [])
            const payload: Partial<RecordingViewedProps> = {
                load_time: loadTime,
                duration: eventIndex.getDuration(),
                start_time: recordingData.metadata.segments[0]?.startTimeEpochMs,
                end_time: recordingData.metadata.segments.slice(-1)[0]?.endTimeEpochMs,
                page_change_events_length: eventIndex.pageChangeEvents().length,
                recording_width: eventIndex.getRecordingMetadata(0)[0]?.width,
                source: source,
            }
            posthog.capture(`recording ${type}`, payload)
        },
        reportRecordingEventsFetched: ({ numEvents, loadTime }) => {
            posthog.capture(`recording events fetched`, { num_events: numEvents, load_time: loadTime })
        },
        reportRecordingScrollTo: ({ rowIndex }) => {
            posthog.capture(`recording event list scrolled`, { rowIndex })
        },
        reportPayGateShown: (props) => {
            posthog.capture('pay gate shown', props)
        },
        reportPayGateDismissed: (props) => {
            posthog.capture('pay gate dismissed', props)
        },
        reportPersonMerged: (props) => {
            posthog.capture('merge person completed', props)
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
            posthog.capture('recording list fetched', { load_time: loadTime })
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
        reportRecordingConsoleFeedback: ({ response, logCount, question }) => {
            posthog.capture('recording console feedback', { question, response, log_count: logCount })
        },
        reportRecordingConsoleViewed: ({ logCount }) => {
            posthog.capture('recording console logs viewed', { log_count: logCount })
        },
        reportExperimentArchived: ({ experiment }) => {
            posthog.capture('experiment archived', {
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
        reportPrimaryDashboardModalOpened: () => {
            posthog.capture('primary dashboard modal opened')
        },
        reportPrimaryDashboardChanged: () => {
            posthog.capture('primary dashboard changed')
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
        reportDataManagementEventDefinitionsPageClickNestedPropertyDetail: () => {
            posthog.capture('event definitions page event nested property show detail clicked')
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
        reportTeamHasIngestedEvents: () => {
            posthog.capture('team has ingested events')
        },
        reportIngestionSelectPlatformType: ({ platform }) => {
            posthog.capture('ingestion select platform type', {
                platform: platform,
            })
        },
        reportIngestionSelectFrameworkType: ({ framework }) => {
            posthog.capture('ingestion select framework type', {
                framework: framework,
            })
        },
        reportIngestionHelpClicked: ({ type }) => {
            posthog.capture('ingestion help clicked', {
                type: type,
            })
        },
        reportIngestionTryWithBookmarkletClicked: () => {
            posthog.capture('ingestion try posthog with bookmarklet clicked')
        },
        reportIngestionContinueWithoutVerifying: () => {
            posthog.capture('ingestion continue without verifying')
        },
        reportIngestionThirdPartyAboutClicked: ({ name }) => {
            posthog.capture('ingestion third party about clicked', {
                name: name,
            })
        },
        reportIngestionThirdPartyConfigureClicked: ({ name }) => {
            posthog.capture('ingestion third party configure clicked', {
                name: name,
            })
        },
        reportIngestionThirdPartyPluginInstalled: ({ name }) => {
            posthog.capture('report ingestion third party plugin installed', {
                name: name,
            })
        },
        reportFailedToCreateFeatureFlagWithCohort: ({ detail, code }) => {
            posthog.capture('failed to create feature flag with cohort', { detail, code })
        },
        reportInviteMembersButtonClicked: () => {
            posthog.capture('invite members button clicked')
        },
        reportIngestionSidebarButtonClicked: ({ name }) => {
            posthog.capture('ingestion sidebar button clicked', {
                name: name,
            })
        },
    }),
})
