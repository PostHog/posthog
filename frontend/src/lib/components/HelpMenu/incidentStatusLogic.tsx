import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

// eslint-disable-next-line import/no-cycle
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { Region } from '~/types'

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

// A user-facing warning derived from an ongoing incident that affects a specific component.
export interface ComponentIncidentAlert {
    title: string
    description: string
    severity: 'warning' | 'error'
}

export const STATUS_PAGE_BASE = 'https://www.posthogstatus.com'
const REFRESH_INTERVAL = 60 * 1000 * 5 // 5 minutes

const DEFAULT_STATUS: NormalizedStatus = 'operational'

// A failed `fetch` to an external host throws a `TypeError` ("Failed to fetch", "NetworkError when
// attempting to fetch resource", "Load failed", ...). These are expected and outside our control —
// ad blockers, tracking-protection extensions, DNS hiccups, brief status-page outages — so they're
// noise in error tracking rather than real defects. A genuine bug here would surface as a different
// error type (e.g. a `SyntaxError` from `response.json()`), which we still want to capture.
function isNetworkError(error: unknown): boolean {
    return error instanceof TypeError
}

let currentStatus: NormalizedStatus = DEFAULT_STATUS

export function setIncidentStatus(status: NormalizedStatus): void {
    currentStatus = status
}

export function getIncidentStatus(): NormalizedStatus {
    return currentStatus
}

// incident.io component name for the PostHog AI service. An incident is treated as affecting AI only
// when it tags a component with this exact name under the current region's group (see getRelevantGroupName).
export const AI_COMPONENT_NAME = 'PostHog AI'

// incident.io component group name (text only — the status page suffixes a region flag emoji we strip
// on the API side via normalizeGroupName) for each cloud region.
const GROUP_NAME_BY_REGION: Partial<Record<Region, string>> = {
    [Region.US]: 'US Cloud',
    [Region.EU]: 'EU Cloud',
}

// Resolve the incident.io component group from preflight. US and EU cloud each see their own region's
// incidents; everything else (local dev, self-hosted, Storybook, unknown deployments) sees nothing.
function getRelevantGroupName(region: Region | null | undefined): string | null {
    if (!region) {
        return null
    }
    return GROUP_NAME_BY_REGION[region] ?? null
}

// Map hostname to the region-specific status page path (incident.io sub-pages)
const REGION_PATH_MAP: Record<string, string> = {
    'us.posthog.com': '/us',
    'eu.posthog.com': '/eu',
    localhost: '/us', // Default to US for local dev
    '127.0.0.1': '/us', // Storybook CI runs at 127.0.0.1:6006
}

// Reduce an incident.io group_name to its text, dropping the region flag emoji and surrounding
// whitespace, so it can be compared against the emoji-free names in GROUP_NAME_BY_REGION.
function normalizeGroupName(name: string): string {
    return name.replace(/[^\p{L}\p{N}\s]/gu, '').trim()
}

// Region-specific status page URL, falling back to the root page for unknown (self-hosted) hosts
export function getStatusPageUrl(): string {
    return `${STATUS_PAGE_BASE}${REGION_PATH_MAP[window.location.hostname] ?? ''}`
}

function hasRelevantComponents(affectedComponents: AffectedComponent[], relevantGroupName: string | null): boolean {
    if (!relevantGroupName) {
        // No region (local dev, self-hosted, unknown) — cloud incidents aren't relevant
        return false
    }
    // If no affected components, show the incident (it's global)
    if (affectedComponents.length === 0) {
        return true
    }
    return affectedComponents.some((component) => normalizeGroupName(component.group_name ?? '') === relevantGroupName)
}

function getWorstStatusForRegion(summary: Summary, relevantGroupName: string | null): NormalizedStatus {
    // Filter incidents to only those affecting the current region
    const relevantIncidents = summary.ongoing_incidents.filter((incident) =>
        hasRelevantComponents(incident.affected_components, relevantGroupName)
    )
    const relevantMaintenances = summary.in_progress_maintenances.filter((maintenance) =>
        hasRelevantComponents(maintenance.affected_components, relevantGroupName)
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

// The AI component tagged on this incident for the current region, if any.
function matchedAiComponent(incident: Incident, relevantGroupName: string | null): AffectedComponent | undefined {
    if (!relevantGroupName) {
        // No region (local dev, self-hosted, unknown) — cloud AI incidents aren't relevant.
        return undefined
    }
    return incident.affected_components.find(
        (component) =>
            component.name === AI_COMPONENT_NAME && normalizeGroupName(component.group_name ?? '') === relevantGroupName
    )
}

function componentStatusToSeverity(status: ComponentStatus): ComponentIncidentAlert['severity'] {
    return status === 'partial_outage' || status === 'full_outage' ? 'error' : 'warning'
}

function getAiIncidentAlerts(summary: Summary | null, relevantGroupName: string | null): ComponentIncidentAlert[] {
    if (!summary) {
        return []
    }
    return summary.ongoing_incidents.reduce<ComponentIncidentAlert[]>((alerts, incident) => {
        const component = matchedAiComponent(incident, relevantGroupName)
        if (component) {
            alerts.push({
                title: incident.name,
                description: incident.last_update_message,
                severity: componentStatusToSeverity(component.current_status),
            })
        }
        return alerts
    }, [])
}

export const incidentStatusLogic = kea<incidentStatusLogicType>([
    path(['lib', 'components', 'HelpMenu', 'incidentStatusLogic']),

    connect(() => ({
        values: [superpowersLogic, ['fakeStatusOverride', 'superpowersEnabled'], preflightLogic, ['preflight']],
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
                    // via the rawStatus selector). We report a reachable-but-erroring status page (non-2xx)
                    // and unexpected errors, but skip the expected network-level failures so they don't
                    // pollute error tracking as a recurring issue.
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
                        if (!isNetworkError(error)) {
                            posthog.captureException(error)
                        }
                        return null
                    }
                },
            },
        ],
    })),

    selectors({
        statusPageUrl: [() => [], (): string => getStatusPageUrl()],
        relevantGroupName: [
            (s) => [s.preflight],
            (preflight): string | null => getRelevantGroupName(preflight?.region),
        ],
        rawStatus: [
            (s) => [s.summary, s.relevantGroupName],
            (summary: Summary | null, relevantGroupName): NormalizedStatus => {
                if (!summary) {
                    return 'operational'
                }
                return getWorstStatusForRegion(summary, relevantGroupName)
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
        aiIncidentAlerts: [
            (s) => [s.summary, s.relevantGroupName],
            (summary: Summary | null, relevantGroupName): ComponentIncidentAlert[] =>
                getAiIncidentAlerts(summary, relevantGroupName),
        ],
        statusDescription: [
            (s) => [s.summary, s.status, s.relevantGroupName],
            (summary, status, relevantGroupName): string | null => {
                if (!summary) {
                    return null
                }
                if (status === 'operational') {
                    return 'All systems operational'
                }
                // Filter to only count incidents/maintenances relevant to this region
                const incidentCount = summary.ongoing_incidents.filter((incident: Incident) =>
                    hasRelevantComponents(incident.affected_components, relevantGroupName)
                ).length
                const maintenanceCount = summary.in_progress_maintenances.filter((maintenance: Maintenance) =>
                    hasRelevantComponents(maintenance.affected_components, relevantGroupName)
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
