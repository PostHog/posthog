/**
 * Product RBAC for gated widget types. New types: extend union here — see products/dashboards/CONTRIBUTING.md.
 */
export type DashboardWidgetProductAccess = 'error_tracking' | 'session_recording' | 'experiment' | 'survey' | 'logs'
