import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelStatusLogicType } from './sidePanelStatusLogicType'

export type SPIndicator = 'none' | 'minor' | 'major'

export type SPComponentStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'

// incident.io types
export type IncidentIoComponentStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'full_outage'
export type IncidentIoImpact = 'partial_outage' | 'degraded_performance' | 'full_outage'
export type IncidentIoIncidentStatus = 'investigating' | 'identified' | 'monitoring'
export type IncidentIoMaintenanceStatus = 'maintenance_in_progress' | 'maintenance_scheduled'

export interface IncidentIoAffectedComponent {
    id: string
    name: string
    group_name?: string
    current_status: IncidentIoComponentStatus
}

export interface IncidentIoIncident {
    id: string
    name: string
    status: IncidentIoIncidentStatus
    url: string
    last_update_at: string
    last_update_message: string
    current_worst_impact: IncidentIoImpact
    affected_components: IncidentIoAffectedComponent[]
}

export interface IncidentIoMaintenance {
    id: string
    name: string
    status: IncidentIoMaintenanceStatus
    last_update_at: string
    last_update_message: string
    url: string
    affected_components: IncidentIoAffectedComponent[]
    started_at?: string
    scheduled_end_at?: string
    starts_at?: string
    ends_at?: string
}

export interface IncidentIoSummary {
    page_title: string
    page_url: string
    ongoing_incidents: IncidentIoIncident[]
    in_progress_maintenances: IncidentIoMaintenance[]
    scheduled_maintenances: IncidentIoMaintenance[]
}

export interface SPSummary {
    // page: SPPage
    components: SPComponent[]
    incidents: SPIncident[]
    scheduled_maintenances: any[]
    status: SPStatus
}

export interface SPComponent {
    id: string
    name: string
    status: SPComponentStatus
    created_at: Date
    updated_at: Date
    position: number
    description: null | string
    showcase: boolean
    start_date: Date | null
    group_id: null | string
    page_id: string
    group: boolean
    only_show_if_degraded: boolean
    components?: string[]
}

export interface SPIncident {
    id: string
    name: string
    status: string
    created_at: Date
    updated_at: Date
    monitoring_at: null
    resolved_at: null
    impact: string
    shortlink: string
    started_at: Date
    page_id: string
    incident_updates: SPIncidentUpdate[]
    components: SPComponent[]
    reminder_intervals: string
}

export interface SPIncidentUpdate {
    id: string
    status: string
    body: string
    incident_id: string
    created_at: Date
    updated_at: Date
    display_at: Date
    affected_components: SPAffectedComponent[]
    deliver_notifications: boolean
    custom_tweet: null
    tweet_id: null
}

export interface SPAffectedComponent {
    code: string
    name: string
    old_status: string
    new_status: string
}

export interface SPStatus {
    indicator: SPIndicator
    description: string
}

export const STATUS_PAGE_BASE = 'https://status.posthog.com'

// NOTE: Test account with some incidents - ask @benjackwhite for access
// export const STATUS_PAGE_BASE = 'https://posthogtesting.statuspage.io'

// incident.io status page
export const INCIDENT_IO_STATUS_PAGE_BASE = 'https://www.posthogstatus.com'

// Map the hostname to relevant groups (found via the summary.json endpoint)
const RELEVANT_GROUPS_MAP = {
    'us.posthog.com': ['41df083ftqt6', 'z0y6m9kyvy3j'],
    'eu.posthog.com': ['c4d9jd1jcx3f', 'nfknrn2bf3yz'],
    localhost: ['f58xx1143yvt', 't3rdjq2z0x7p'], // localhost has IDs for the test status page - that way we really only show it if local dev and overridden to use the other status page
}

export const REFRESH_INTERVAL = 60 * 1000 * 5 // 5 minutes

// Helper to determine worst status from incident.io data
function getWorstIncidentIoStatus(summary: IncidentIoSummary): SPComponentStatus {
    const hasOngoingIncidents = summary.ongoing_incidents.length > 0
    const hasInProgressMaintenance = summary.in_progress_maintenances.length > 0

    if (!hasOngoingIncidents && !hasInProgressMaintenance) {
        return 'operational'
    }

    // Check for worst impact across all ongoing incidents
    for (const incident of summary.ongoing_incidents) {
        if (incident.current_worst_impact === 'full_outage') {
            return 'major_outage'
        }
    }

    for (const incident of summary.ongoing_incidents) {
        if (incident.current_worst_impact === 'partial_outage') {
            return 'partial_outage'
        }
    }

    for (const incident of summary.ongoing_incidents) {
        if (incident.current_worst_impact === 'degraded_performance') {
            return 'degraded_performance'
        }
    }

    // If only maintenance is in progress, show as degraded
    if (hasInProgressMaintenance) {
        return 'degraded_performance'
    }

    return 'operational'
}

export const sidePanelStatusLogic = kea<sidePanelStatusLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelStatusLogic']),
    connect(() => ({
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        loadStatusPage: true,
        setPageVisibility: (visible: boolean) => ({ visible }),
    }),

    reducers(() => ({
        // Persisted copy to avoid flash effect on page load
        status: [
            'operational' as SPComponentStatus,
            { persist: true },
            {
                loadStatusPageSuccess: (_, { statusPage }) => {
                    const relevantGroups = RELEVANT_GROUPS_MAP[window.location.hostname]
                    if (!relevantGroups) {
                        return 'operational'
                    }

                    const componentStatus = statusPage.components.find(
                        ({ group_id, status }) =>
                            group_id && relevantGroups.includes(group_id) && status !== 'operational'
                    )?.status

                    return componentStatus || 'operational'
                },
                loadStatusPageFailure: () => 'operational',
                loadIncidentIoStatusPageSuccess: (_, { incidentIoStatusPage }) => {
                    return getWorstIncidentIoStatus(incidentIoStatusPage)
                },
                loadIncidentIoStatusPageFailure: () => 'operational',
            },
        ],
    })),

    loaders(() => ({
        statusPage: [
            null as SPSummary | null,
            {
                loadStatusPage: async () => {
                    const response = await fetch(`${STATUS_PAGE_BASE}/api/v2/summary.json`)
                    const data: SPSummary = await response.json()

                    return data
                },
            },
        ],
        incidentIoStatusPage: [
            null as IncidentIoSummary | null,
            {
                loadIncidentIoStatusPage: async () => {
                    const response = await fetch(`${INCIDENT_IO_STATUS_PAGE_BASE}/api/v1/summary`)
                    const data: IncidentIoSummary = await response.json()

                    return data
                },
            },
        ],
    })),

    selectors({
        useIncidentIo: [(s) => [s.featureFlags], (featureFlags) => !!featureFlags['incident-io-status-page'] || true],
        statusDescription: [
            (s) => [s.useIncidentIo, s.statusPage, s.incidentIoStatusPage, s.status],
            (useIncidentIo, statusPage, incidentIoStatusPage, status): string | null => {
                if (useIncidentIo) {
                    if (!incidentIoStatusPage) {
                        return null
                    }
                    if (status === 'operational') {
                        return 'All systems operational'
                    }
                    const incidentCount = incidentIoStatusPage.ongoing_incidents.length
                    const maintenanceCount = incidentIoStatusPage.in_progress_maintenances.length
                    if (incidentCount > 0) {
                        return `${incidentCount} ongoing incident${incidentCount > 1 ? 's' : ''}`
                    }
                    if (maintenanceCount > 0) {
                        return `${maintenanceCount} maintenance${maintenanceCount > 1 ? 's' : ''} in progress`
                    }
                    return 'All systems operational'
                }
                return statusPage?.status.description
                    ? statusPage.status.description.charAt(0).toUpperCase() +
                          statusPage.status.description.slice(1).toLowerCase()
                    : null
            },
        ],
    }),

    listeners(({ actions, cache, values }) => ({
        loadStatusPageSuccess: () => {
            if (!values.useIncidentIo) {
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => actions.loadStatusPage(), REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'refreshTimeout')
            }
        },
        loadIncidentIoStatusPageSuccess: () => {
            if (values.useIncidentIo) {
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => actions.loadIncidentIoStatusPage(), REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'refreshTimeout')
            }
        },
        setPageVisibility: ({ visible }) => {
            if (visible) {
                if (values.useIncidentIo) {
                    actions.loadIncidentIoStatusPage()
                } else {
                    actions.loadStatusPage()
                }
            } else {
                cache.disposables.dispose('refreshTimeout')
            }
        },
    })),

    afterMount(({ actions, cache, values }) => {
        if (values.useIncidentIo) {
            actions.loadIncidentIoStatusPage()
        } else {
            actions.loadStatusPage()
        }
        cache.disposables.add(() => {
            const onVisibilityChange = (): void => {
                actions.setPageVisibility(document.visibilityState === 'visible')
            }
            document.addEventListener('visibilitychange', onVisibilityChange)
            return () => document.removeEventListener('visibilitychange', onVisibilityChange)
        }, 'visibilityListener')
    }),
])
