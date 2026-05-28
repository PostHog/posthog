/**
 * Canonical widget_type keys shipped in this repo.
 * Keep in sync with `EXPECTED_WIDGET_TYPES` in `products/dashboards/backend/widget_registry.py`.
 */
export const EXPECTED_DASHBOARD_WIDGET_TYPES = ['error_tracking_list', 'session_replay_list'] as const

export type ExpectedDashboardWidgetType = (typeof EXPECTED_DASHBOARD_WIDGET_TYPES)[number]
