/* This file contains the logic to report custom frontend events */
import { kea } from 'kea'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
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
} from '~/types'
import { ViewType } from 'scenes/insights/insightLogic'
import dayjs from 'dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

const keyMappingKeys = Object.keys(keyMapping.event)

export enum DashboardEventSource {
    LongPress = 'long_press',
    MoreDropdown = 'more_dropdown',
    DashboardHeader = 'dashboard_header',
    Hotkey = 'hotkey',
    InputEnter = 'input_enter',
    Toast = 'toast',
    Browser = 'browser',
    AddDescription = 'add_description',
}

export const eventUsageLogic = kea<
    eventUsageLogicType<AnnotationType, FilterType, DashboardType, PersonType, DashboardMode, DashboardEventSource>
>({
    connect: [preflightLogic],
    actions: {
        reportAnnotationViewed: (annotations: AnnotationType[] | null) => ({ annotations }),
        reportPersonDetailViewed: (person: PersonType) => ({ person }),
        reportInsightViewed: (filters: Partial<FilterType>, isFirstLoad: boolean) => ({ filters, isFirstLoad }),
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
            success: boolean,
            error?: string
        ) => ({
            eventCount,
            actionCount,
            interval,
            success,
            error,
        }),
        reportPersonPropertyUpdated: (
            action: 'added' | 'updated' | 'removed',
            totalProperties: number,
            oldPropertyType?: string,
            newPropertyType?: string
        ) => ({ action, totalProperties, oldPropertyType, newPropertyType }),
        reportDashboardViewed: (dashboard: DashboardType, hasShareToken: boolean) => ({ dashboard, hasShareToken }),
        reportDashboardModeToggled: (mode: DashboardMode, source: DashboardEventSource | null) => ({ mode, source }),
        reportDashboardRefreshed: (lastRefreshed?: string | dayjs.Dayjs | null) => ({ lastRefreshed }),
        reportDashboardDateRangeChanged: (dateFrom?: string | dayjs.Dayjs, dateTo?: string | dayjs.Dayjs | null) => ({
            dateFrom,
            dateTo,
        }),
        reportDashboardPinToggled: (pinned: boolean, source: 'more_dropdown' | 'main_nav' | 'dashboards_list') => ({
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
        reportInsightFilterAdded: (newLength: number) => ({ newLength }),
        reportInsightFilterSet: (filters: Array<{ id: string | number | null; type?: EntityType }>) => ({ filters }),
        reportEntityFilterVisibilitySet: (index: number, visible: boolean) => ({ index, visible }),
        reportPropertySelectOpened: true,
        reportCreatedDashboardFromModal: true,
        reportSavedInsightToDashboard: true,
        reportInsightsTabReset: true,
        reportInsightsControlsCollapseToggle: (collapsed: boolean) => ({ collapsed }),
        reportInsightsTableCalcToggled: (mode: string) => ({ mode }),
    },
    listeners: {
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
                    created_by_me:
                        annotation.created_by &&
                        annotation.created_by !== 'local' &&
                        annotation.created_by?.uuid === userLogic.values.user?.uuid,
                    creation_type: annotation.creation_type,
                    created_at: annotation.created_at,
                    updated_at: annotation.updated_at,
                }
                posthog.capture('annotation viewed', properties)
            }
        },
        reportPersonDetailViewed: async ({ person }: { person: PersonType }, breakpoint) => {
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
                is_identified: person.is_identified,
                has_email: !!person.properties.email,
                has_name: !!person.properties.name,
                custom_properties_count,
                posthog_properties_count,
            }
            posthog.capture('person viewed', properties)
        },
        reportInsightViewed: async ({ filters, isFirstLoad }, breakpoint) => {
            await breakpoint(500) // Debounce to avoid noisy events from changing filters multiple times

            // Reports `insight viewed` event
            const { display, interval, date_from, date_to, filter_test_accounts, formula, insight } = filters

            const properties: Record<string, any> = {
                is_first_component_load: isFirstLoad,
                insight,
                display,
                interval,
                date_from,
                date_to,
                filter_test_accounts,
                formula,
                filters_count: filters.properties?.length || 0, // Only counts general filters (i.e. not per-event filters)
                events_count: filters.events?.length || 0, // Number of event lines in insights graph; number of steps in funnel
                actions_count: filters.actions?.length || 0, // Number of action lines in insights graph; number of steps in funnel
            }

            properties.total_event_actions_count = (properties.events_count || 0) + (properties.actions_count || 0)

            let totalEventActionFilters = 0
            filters.events?.forEach((event) => {
                if (event.properties?.length) {
                    totalEventActionFilters += event.properties.length
                }
            })
            filters.actions?.forEach((action) => {
                if (action.properties?.length) {
                    totalEventActionFilters += action.properties.length
                }
            })

            // The total # of filters applied on events and actions.
            properties.total_event_action_filters_count = totalEventActionFilters

            // Custom properties for each insight
            if (insight === 'TRENDS') {
                properties.breakdown_type = filters.breakdown_type
                properties.breakdown = filters.breakdown
            } else if (insight === 'SESSIONS') {
                properties.session_distribution = filters.session
            } else if (insight === 'FUNNELS') {
                properties.session_distribution = filters.session
            } else if (insight === 'RETENTION') {
                properties.period = filters.period
                properties.date_to = filters.date_to
                properties.retention_type = filters.retentionType
                const cohortizingEvent = filters.target_entity
                const retainingEvent = filters.returning_entity
                properties.same_retention_and_cohortizing_event =
                    cohortizingEvent?.id == retainingEvent?.id && cohortizingEvent?.type == retainingEvent?.type
            } else if (insight === 'PATHS') {
                properties.path_type = filters.path_type
                properties.has_start_point = !!filters.start_point
            } else if (insight === 'STICKINESS') {
                properties.stickiness_days = filters.stickiness_days
            }

            posthog.capture('insight viewed', properties)
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
                has_share_token: hasShareToken, // if the dashboard is being viewed in `public` mode
            }

            for (const item of dashboard.items) {
                const key = `${item.filters?.insight?.toLowerCase() || ViewType.TRENDS}_count`
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
        reportFunnelCalculated: async ({ eventCount, actionCount, interval, success, error }) => {
            posthog.capture('funnel result calculated', {
                event_count: eventCount,
                action_count: actionCount,
                total_count_actions_events: eventCount + actionCount,
                interval: interval,
                success: success,
                error: error,
            })
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
            if (preflightLogic.values.realm === 'cloud') {
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
        reportInsightsControlsCollapseToggle: async (payload) => {
            posthog.capture('insight controls collapse toggled', payload)
        },
        reportInsightsTableCalcToggled: async (payload) => {
            posthog.capture('insights table calc toggled', payload)
        },
    },
})
