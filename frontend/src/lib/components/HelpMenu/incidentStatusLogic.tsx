import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

// eslint-disable-next-line import/no-cycle
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'

import type { incidentStatusLogicType } from './incidentStatusLogicType'

// Raw status page API types
export type ComponentStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'full_outage'
export type Impact = 'partial_outage' | 'degraded_performance' | 'full_outage'
export type IncidentStatus = 'investigating' | 'identified' | 'monitoring'
export type MaintenanceStatus = 'maintenance_in_progress' | 'maintenance_scheduled'

// Normalized status for display
export type NormalizedStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'

export interface AffectedComponent {
    id: string
    name: string
    group_name?: string
    current_status: ComponentStatus
}

export interface Incident {
    id: string
    name: string
    status: IncidentStatus
    url: string
    last_update_at: string
    last_update_message: string
    current_worst_impact: Impact
    affected_components: AffectedComponent[]
}

export interface Maintenance {
    id: string
    name: string
    status: MaintenanceStatus
    last_update_at: string
    last_update_message: string
    url: string
    affected_components: AffectedComponent[]
    started_at?: string
    scheduled_end_at?: string
    starts_at?: string
    ends_at?: string
}

export interface Summary {
    page_title: string
    page_url: string
    ongoing_incidents: Incident[]
    in_progress_maintenances: Maintenance[]
    scheduled_maintenances: Maintenance[]
}

export const STATUS_PAGE_BASE = 'https://www.posthogstatus.com'
const REFRESH_INTERVAL = 60 * 1000 * 5 // 5 minutes

const DEFAULT_STATUS: NormalizedStatus = 'operational'

let currentStatus: NormalizedStatus = DEFAULT_STATUS

export function setIncidentStatus(status: NormalizedStatus): void {
    currentStatus = status
}

export function getIncidentStatus(): NormalizedStatus {
    return currentStatus
}

// Map hostname to the group_name used in incident.io
const RELEVANT_GROUP_NAME_MAP: Record<string, string> = {
    'us.posthog.com': 'US Cloud 🇺🇸',
    'eu.posthog.com': 'EU Cloud 🇪🇺',
    localhost: 'US Cloud 🇺🇸', // Default to US for local dev
    '127.0.0.1': 'US Cloud 🇺🇸', // Storybook CI runs at 127.0.0.1:6006
}

// Map hostname to the region-specific status page path (incident.io sub-pages)
const REGION_PATH_MAP: Record<string, string> = {
    'us.posthog.com': '/us',
    'eu.posthog.com': '/eu',
    localhost: '/us', // Default to US for local dev
    '127.0.0.1': '/us', // Storybook CI runs at 127.0.0.1:6006
}

function getRelevantGroupName(): string | null {
    return RELEVANT_GROUP_NAME_MAP[window.location.hostname] || null
}

// Region-specific status page URL, falling back to the root page for unknown (self-hosted) hosts
export function getStatusPageUrl(): string {
    return `${STATUS_PAGE_BASE}${REGION_PATH_MAP[window.location.hostname] ?? ''}`
}

function hasRelevantComponents(affectedComponents: AffectedComponent[]): boolean {
    const relevantGroupName = getRelevantGroupName()
    if (!relevantGroupName) {
        // Unknown hostname (self-hosted) — cloud incidents aren't relevant
        return false
    }
    // If no affected components, show the incident (it's global)
    if (affectedComponents.length === 0) {
        return true
    }
    return affectedComponents.some((component) => component.group_name === relevantGroupName)
}

function getWorstStatusForRegion(summary: Summary): NormalizedStatus {
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

export const incidentStatusLogic = kea<incidentStatusLogicType>([
    path(['lib', 'components', 'HelpMenu', 'incidentStatusLogic']),

    connect(() => ({
        values: [superpowersLogic, ['fakeStatusOverride', 'superpowersEnabled']],
    })),

    actions({
        setPageVisibility: (visible: boolean) => ({ visible }),
    }),

    loaders(() => ({
        summary: [
            null as Summary | null,
            {
                loadSummary: async () => {
                    // The incident.io status page is external (posthogstatus.com), so the fetch can fail
                    // for reasons outside our control: ad blockers, tracking-protection extensions, DNS
                    // hiccups, brief status-page outages. Swallow the failure (degrading to 'operational'
                    // via the rawStatus selector) but still report to error tracking so we keep visibility.
                    try {
                        const response = await fetch(`${STATUS_PAGE_BASE}/api/v1/summary`)
                        if (!response.ok) {
                            posthog.captureException(
                                new Error(`incident.io summary fetch returned ${response.status}`),
                                { status: response.status, statusText: response.statusText }
                            )
                            return null
                        }
                        const data: Summary = await response.json()
                        return data
                    } catch (error) {
                        posthog.captureException(error)
                        return null
                    }
                },
            },
        ],
    })),

    selectors({
        statusPageUrl: [() => [], (): string => getStatusPageUrl()],
        rawStatus: [
            (s) => [s.summary],
            (summary: Summary | null): NormalizedStatus => {
                if (!summary) {
                    return 'operational'
                }
                return getWorstStatusForRegion(summary)
            },
        ],
        status: [
            (s) => [s.rawStatus, s.fakeStatusOverride, s.superpowersEnabled],
            (rawStatus, fakeStatusOverride, superpowersEnabled): NormalizedStatus => {
                if (superpowersEnabled && fakeStatusOverride !== 'none') {
                    return fakeStatusOverride as NormalizedStatus
                }
                return rawStatus
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
                const incidentCount = summary.ongoing_incidents.filter((incident: Incident) =>
                    hasRelevantComponents(incident.affected_components)
                ).length
                const maintenanceCount = summary.in_progress_maintenances.filter((maintenance: Maintenance) =>
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

    listeners(({ actions, cache, values }) => ({
        loadSummarySuccess: () => {
            setIncidentStatus(values.status)

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
