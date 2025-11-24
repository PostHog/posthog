import { actions, afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { sidePanelStatusIncidentIoLogicType } from './sidePanelStatusIncidentIoLogicType'

// Status types
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

// Normalized status for display
export type NormalizedStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'

export const INCIDENT_IO_STATUS_PAGE_BASE = 'https://www.posthogstatus.com'
export const REFRESH_INTERVAL = 60 * 1000 * 5 // 5 minutes

// Map hostname to the group_name used in incident.io
const RELEVANT_GROUP_NAME_MAP: Record<string, string> = {
    'us.posthog.com': 'US Cloud 🇺🇸',
    'eu.posthog.com': 'EU Cloud 🇪🇺',
    localhost: 'US Cloud 🇺🇸', // Default to US for local dev
}

function getRelevantGroupName(): string | null {
    return RELEVANT_GROUP_NAME_MAP[window.location.hostname] || null
}

function hasRelevantComponents(affectedComponents: IncidentIoAffectedComponent[]): boolean {
    const relevantGroupName = getRelevantGroupName()
    if (!relevantGroupName) {
        // If no mapping, show all incidents
        return true
    }
    // If no affected components, show the incident (it's global)
    if (affectedComponents.length === 0) {
        return true
    }
    return affectedComponents.some((component) => component.group_name === relevantGroupName)
}

function getWorstStatusForRegion(summary: IncidentIoSummary): NormalizedStatus {
    // Filter incidents to only those affecting the current region
    const relevantIncidents = summary.ongoing_incidents.filter((incident) =>
        hasRelevantComponents(incident.affected_components)
    )
    const relevantMaintenances = summary.in_progress_maintenances.filter((maintenance) =>
        hasRelevantComponents(maintenance.affected_components)
    )

    const hasOngoingIncidents = relevantIncidents.length > 0
    const hasInProgressMaintenance = relevantMaintenances.length > 0

    if (!hasOngoingIncidents && !hasInProgressMaintenance) {
        return 'operational'
    }

    // Check for worst impact across relevant ongoing incidents
    for (const incident of relevantIncidents) {
        if (incident.current_worst_impact === 'full_outage') {
            return 'major_outage'
        }
    }

    for (const incident of relevantIncidents) {
        if (incident.current_worst_impact === 'partial_outage') {
            return 'partial_outage'
        }
    }

    for (const incident of relevantIncidents) {
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

export const sidePanelStatusIncidentIoLogic = kea<sidePanelStatusIncidentIoLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelStatusIncidentIoLogic']),

    actions({
        setPageVisibility: (visible: boolean) => ({ visible }),
    }),

    loaders(() => ({
        summary: [
            null as IncidentIoSummary | null,
            {
                loadSummary: async () => {
                    const response = await fetch(`${INCIDENT_IO_STATUS_PAGE_BASE}/api/v1/summary`)
                    const data: IncidentIoSummary = await response.json()
                    return data
                },
            },
        ],
    })),

    selectors({
        status: [
            (s) => [s.summary],
            (summary: IncidentIoSummary | null): NormalizedStatus => {
                if (!summary) {
                    return 'operational'
                }
                return getWorstStatusForRegion(summary)
            },
        ],
        statusDescription: [
            (s) => [s.summary, s.status],
            (summary, status): string | null => {
                if (!summary) {
                    return null
                }
                if (status === 'operational') {
                    return 'All systems operational'
                }
                // Filter to only count incidents/maintenances relevant to this region
                const incidentCount = summary.ongoing_incidents.filter((incident: IncidentIoIncident) =>
                    hasRelevantComponents(incident.affected_components)
                ).length
                const maintenanceCount = summary.in_progress_maintenances.filter((maintenance: IncidentIoMaintenance) =>
                    hasRelevantComponents(maintenance.affected_components)
                ).length
                if (incidentCount > 0) {
                    return `${incidentCount} ongoing incident${incidentCount > 1 ? 's' : ''}`
                }
                if (maintenanceCount > 0) {
                    return `${maintenanceCount} maintenance${maintenanceCount > 1 ? 's' : ''} in progress`
                }
                return 'All systems operational'
            },
        ],
    }),

    listeners(({ actions, cache }) => ({
        loadSummarySuccess: () => {
            cache.disposables.add(() => {
                const timerId = setTimeout(() => actions.loadSummary(), REFRESH_INTERVAL)
                return () => clearTimeout(timerId)
            }, 'refreshTimeout')
        },
        setPageVisibility: ({ visible }) => {
            if (visible) {
                actions.loadSummary()
            } else {
                cache.disposables.dispose('refreshTimeout')
            }
        },
    })),

    afterMount(({ actions, cache }) => {
        actions.loadSummary()
        cache.disposables.add(() => {
            const onVisibilityChange = (): void => {
                actions.setPageVisibility(document.visibilityState === 'visible')
            }
            document.addEventListener('visibilitychange', onVisibilityChange)
            return () => document.removeEventListener('visibilitychange', onVisibilityChange)
        }, 'visibilityListener')
    }),
])
