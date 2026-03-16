// Raw incident.io API types
export type IncidentIoComponentStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'full_outage'
export type IncidentIoImpact = 'partial_outage' | 'degraded_performance' | 'full_outage'
export type IncidentIoIncidentStatus = 'investigating' | 'identified' | 'monitoring'
export type IncidentIoMaintenanceStatus = 'maintenance_in_progress' | 'maintenance_scheduled'

// Normalized status for display
export type NormalizedStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'

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

export const INCIDENT_IO_STATUS_PAGE_BASE = 'https://www.posthogstatus.com'
export const REFRESH_INTERVAL = 60 * 1000 * 5 // 5 minutes

const DEFAULT_STATUS: NormalizedStatus = 'operational'

let currentStatus: NormalizedStatus = DEFAULT_STATUS

export function setIncidentStatus(status: NormalizedStatus): void {
    currentStatus = status
}

export function getIncidentStatus(): NormalizedStatus {
    return currentStatus
}
