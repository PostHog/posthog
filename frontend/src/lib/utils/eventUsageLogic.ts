/* This file contains the logic to report custom frontend events */
import { kea } from 'kea'
import { isPostHogProp, keyMappingKeys } from 'lib/components/PropertyKeyInfo'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'
import { eventUsageLogicType } from './eventUsageLogicType'
import {
    AnnotationType,
    FilterType,
    DashboardType,
    PersonType,
    DashboardMode,
    HotKeys,
    GlobalHotKeys,
    EntityType,
    InsightModel,
    InsightType,
    PropertyFilter,
    HelpType,
    SessionPlayerData,
    AvailableFeature,
    SessionRecordingUsageType,
    FunnelCorrelation,
    ItemMode,
    AnyPropertyFilter,
} from '~/types'
import { dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import type { PersonsModalParams } from 'scenes/trends/personsModalLogic'
import { EventIndex } from '@posthog/react-rrweb-player'

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
    RecordingsList = 'recordings_list', // New recordings list page
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

function flattenProperties(properties: PropertyFilter[]): string[] {
    const output = []
    for (const prop of properties || []) {
        if (isPostHogProp(prop.key)) {
            output.push(prop.key)
        } else {
            output.push('redacted') // Custom property names are not reported
        }
    }
    return output
}

function hasGroupProperties(properties: AnyPropertyFilter[] | undefined): boolean {
    return !!properties && properties.some((property) => property.group_type_index != undefined)
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
        insight,
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

    for (const entity of entities) {
        properties_local = properties_local.concat(flattenProperties(entity.properties || []))

        using_groups = using_groups || hasGroupProperties(entity.properties || [])
        if (entity.math_group_type_index != undefined) {
            aggregating_by_groups = true
        }
    }
    const properties_global = flattenProperties(properties)

    return {
        insight,
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
        properties_all: properties_global.concat(properties_local), // Global and local properties together
        aggregating_by_groups,
        breakdown_by_groups,
        using_groups: using_groups || aggregating_by_groups || breakdown_by_groups,
    }
}

export const eventUsageLogic = kea<
    eventUsageLogicType<
        DashboardEventSource,
        GraphSeriesAddedSource,
        RecordingWatchedSource,
        SessionRecordingFilterType
    >
>({
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
            delay, // Number of delayed seconds to report event (useful to measure insights where users don't navigate immediately away)
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
        reportDashboardViewed: (dashboard: DashboardType, hasShareToken: boolean) => ({ dashboard, hasShareToken }),
        reportDashboardModeToggled: (mode: DashboardMode, source: DashboardEventSource | null) => ({ mode, source }),
        reportDashboardRefreshed: (lastRefreshed?: string | dayjs.Dayjs | null) => ({ lastRefreshed }),
        reportDashboardItemRefreshed: (dashboardItem: InsightModel) => ({ dashboardItem }),
        reportDashboardDateRangeChanged: (dateFrom?: string | dayjs.Dayjs, dateTo?: string | dayjs.Dayjs | null) => ({
            dateFrom,
            dateTo,
        }),
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
        reportHotkeyNavigation: (scope: 'global' | 'insights', hotkey: HotKeys | GlobalHotKeys) => ({ scope, hotkey }),
        reportIngestionLandingSeen: (isGridView: boolean) => ({ isGridView }),
        reportTimezoneComponentViewed: (
            component: 'label' | 'indicator',
            project_timezone?: string,
            device_timezone?: string
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
        reportInsightViewed: async (
            { insightModel, filters, insightMode, isFirstLoad, fromDashboard, delay, changedFilters },
            breakpoint
        ) => {
            if (!delay) {
                await breakpoint(500) // Debounce to avoid noisy events from changing filters multiple times
            }

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
                properties.has_funnel_filter = !!filters.funnel_filter
                properties.funnel_paths = filters.funnel_paths
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
        reportDashboardViewed: async ({ dashboard, hasShareToken }, breakpoint) => {
            await breakpoint(500) // Debounce to avoid noisy events from continuous navigation
            const { created_at, is_shared, pinned, creation_mode } = dashboard
            const properties: Record<string, any> = {
                created_at,
                is_shared,
                pinned,
                creation_mode,
                sample_items_count: 0,
                item_count: dashboard.items.length,
                created_by_system: !dashboard.created_by,
                has_share_token: hasShareToken,
            }

            for (const item of dashboard.items) {
                const key = `${item.filters?.insight?.toLowerCase() || InsightType.TRENDS}_count`
                if (!properties[key]) {
                    properties[key] = 1
                } else {
                    properties[key] += 1
                }
                properties.sample_items_count += item.is_sample ? 1 : 0
            }

            posthog.capture('viewed dashboard', properties)
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
        reportHotkeyNavigation: async (payload) => {
            posthog.capture('hotkey navigation', payload)
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
        reportIngestionLandingSeen: async ({ isGridView }) => {
            posthog.capture('ingestion landing seen', { grid_view: isGridView })
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
            // @ts-ignore
            const eventIndex = new EventIndex(recordingData?.snapshots || [])
            const payload: Partial<RecordingViewedProps> = {
                load_time: loadTime,
                duration: eventIndex.getDuration(),
                start_time: recordingData?.session_recording?.segments[0]?.startTimeEpochMs,
                end_time: recordingData?.session_recording?.segments.slice(-1)[0]?.endTimeEpochMs,
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
    }),
})
