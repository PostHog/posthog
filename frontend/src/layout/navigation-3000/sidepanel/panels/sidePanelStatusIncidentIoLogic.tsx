import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

// eslint-disable-next-line import/no-cycle
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'

import {
    INCIDENT_IO_STATUS_PAGE_BASE,
    IncidentIoAffectedComponent,
    IncidentIoIncident,
    IncidentIoMaintenance,
    IncidentIoSummary,
    NormalizedStatus,
    REFRESH_INTERVAL,
    setIncidentStatus,
} from '~/layout/navigation-3000/incident/incidentStatus'

import type { sidePanelStatusIncidentIoLogicType } from './sidePanelStatusIncidentIoLogicType'

// Map hostname to the group_name used in incident.io
const RELEVANT_GROUP_NAME_MAP: Record<string, string> = {
    'us.posthog.com': 'US Cloud 🇺🇸',
    'eu.posthog.com': 'EU Cloud 🇪🇺',
    localhost: 'US Cloud 🇺🇸', // Default to US for local dev
    '127.0.0.1': 'US Cloud 🇺🇸', // Storybook CI runs at 127.0.0.1:6006
}

function getRelevantGroupName(): string | null {
    return RELEVANT_GROUP_NAME_MAP[window.location.hostname] || null
}

function hasRelevantComponents(affectedComponents: IncidentIoAffectedComponent[]): boolean {
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

    connect(() => ({
        values: [superpowersLogic, ['fakeStatusOverride', 'superpowersEnabled']],
    })),

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
        rawStatus: [
            (s) => [s.summary],
            (summary: IncidentIoSummary | null): NormalizedStatus => {
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
