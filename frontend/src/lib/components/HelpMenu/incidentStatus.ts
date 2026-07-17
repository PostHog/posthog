// Leaf module for the incident status shared between incidentStatusLogic (which polls the
// status page and writes here) and LemonToast (which reads it to decorate error toasts).
// Deliberately logic-free: LemonToast is imported by virtually every bundle, and importing
// the full incidentStatusLogic from it would drag the help-menu/superpowers/MCP-hint graph
// (including eventUsageLogic and the taxonomy JSON) into all of them.

export type NormalizedStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'

export const STATUS_PAGE_BASE = 'https://www.posthogstatus.com'

export const DEFAULT_STATUS: NormalizedStatus = 'operational'

let currentStatus: NormalizedStatus = DEFAULT_STATUS

export function setIncidentStatus(status: NormalizedStatus): void {
    currentStatus = status
}

export function getIncidentStatus(): NormalizedStatus {
    return currentStatus
}
