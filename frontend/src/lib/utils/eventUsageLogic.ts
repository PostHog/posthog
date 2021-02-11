/* This file contains the logic to report custom frontend events */
import { kea } from 'kea'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'
import { eventUsageLogicType } from './eventUsageLogicType'
import { AnnotationType, FilterType, DashboardType, PersonType } from '~/types'
import { ViewType } from 'scenes/insights/insightLogic'

const keyMappingKeys = Object.keys(keyMapping.event)

export const eventUsageLogic = kea<eventUsageLogicType<AnnotationType, FilterType, DashboardType, PersonType>>({
    actions: {
        reportAnnotationViewed: (annotations: AnnotationType[] | null) => ({ annotations }),
        reportPersonDetailViewed: (person: PersonType) => ({ person }),
        reportInsightViewed: (filters: Partial<FilterType>, isFirstLoad: boolean) => ({ filters, isFirstLoad }),
        reportDashboardViewed: (dashboard: DashboardType, hasShareToken: boolean) => ({ dashboard, hasShareToken }),
        reportBookmarkletDragged: true,
        reportIngestionBookmarkletCollapsible: (activePanels: string[]) => ({ activePanels }),
        reportProjectCreationSubmitted: (projectCount: number, nameLength: number) => ({ projectCount, nameLength }),
        reportDemoWarningDismissed: (key: string) => ({ key }),
        reportOnboardingStepTriggered: (stepKey: string, extra_args: Record<string, string | number | boolean>) => ({
            stepKey,
            extra_args,
        }),
        reportBulkInviteAttempted: (inviteesCount: number, namesCount: number) => ({ inviteesCount, namesCount }),
        reportInviteAttempted: (nameProvided: boolean, instanceEmailAvailable: boolean) => ({
            nameProvided,
            instanceEmailAvailable,
        }),
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
                    created_by_me: annotation.created_by && annotation.created_by?.id === userLogic.values.user?.id,
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
            const { display, interval, date_from, date_to, shown_as } = filters

            // DEPRECATED: Remove when releasing `remove-shownas`
            // Support for legacy `shown_as` property in a way that ensures standardized data reporting
            let { insight } = filters
            const SHOWN_AS_MAPPING: Record<string, 'TRENDS' | 'LIFECYCLE' | 'STICKINESS'> = {
                Volume: 'TRENDS',
                Lifecycle: 'LIFECYCLE',
                Stickiness: 'STICKINESS',
            }
            if (shown_as) {
                insight = SHOWN_AS_MAPPING[shown_as]
            }

            const properties: Record<string, any> = {
                is_first_component_load: isFirstLoad,
                insight,
                display,
                interval,
                date_from,
                date_to,
                filters, // See https://github.com/PostHog/posthog/pull/2787#discussion_r556346868 for details
                filters_count: filters.properties?.length || 0, // Only counts general filters (i.e. not per-event filters)
                events_count: filters.events?.length || 0, // Number of event lines in insights graph; number of steps in funnel
                actions_count: filters.actions?.length || 0, // Number of action lines in insights graph; number of steps in funnel
            }

            properties.total_event_actions_count = (properties.events_count || 0) + (properties.actions_count || 0)

            // Custom properties for each insight
            if (insight === 'TRENDS') {
                properties.breakdown_type = filters.breakdown_type
            } else if (insight === 'SESSIONS') {
                properties.session_distribution = filters.session
            } else if (insight === 'FUNNELS') {
                properties.session_distribution = filters.session
            } else if (insight === 'RETENTION') {
                properties.period = filters.period
                properties.date_to = filters.date_to
                properties.retention_type = filters.retentionType
                const cohortizingEvent = filters.startEntity?.events.length
                    ? filters.startEntity?.events[0].id
                    : filters.startEntity?.actions[0].id
                const retainingEvent = filters.returningEntity?.events.length
                    ? filters.returningEntity?.events[0].id
                    : filters.returningEntity?.actions[0].id
                properties.same_retention_and_cohortizing_event = cohortizingEvent == retainingEvent
            } else if (insight === 'PATHS') {
                properties.path_type = filters.path_type
            }

            posthog.capture('insight viewed', properties)
        },
        reportDashboardViewed: async ({ dashboard, hasShareToken }, breakpoint) => {
            await breakpoint(500) // Debounce to avoid noisy events from continuous navigation
            const { created_at, name, is_shared, pinned } = dashboard
            const properties: Record<string, any> = {
                created_at,
                name: userLogic.values.user?.is_multi_tenancy ? name : undefined, // Don't send name on self-hosted
                is_shared,
                pinned,
                sample_items_count: 0,
                item_count: dashboard.items.length,
                created_by_system: !dashboard.created_by,
                has_share_token: hasShareToken,
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
        reportOnboardingStepTriggered: async ({ stepKey, extra_args }) => {
            // Fired after the user attempts to start an onboarding step (e.g. clicking on create project)
            posthog.capture('onboarding step triggered', { step: stepKey, ...extra_args })
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
    },
})
