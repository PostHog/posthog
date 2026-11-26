import { urls } from 'scenes/urls'

import type { TodayPaneProductSpec, TodayProductPaneConfig } from './todayPaneProducts'

function monitorToolSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.errorTracking() },
        { href: urls.logs() },
        { href: urls.metrics() },
        { href: urls.tracing() },
        { href: urls.uptimeMonitoring() },
    ]
}

function monitorAiProductSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.aiObservabilityDashboard(), section: '/ai-observability' },
        { href: urls.aiObservabilityEvaluations(), section: '/ai-evals' },
        { href: urls.aiObservabilityPrompts(), section: '/prompt-management' },
        { href: urls.aiObservabilityClusters() },
        { href: urls.aiObservabilityPlayground() },
    ]
}

// pinned: shortcut `type` values. Pins are saved with them, so renaming one drops everyone's pins of that type.
export const TODAY_MONITOR_RECENT_TYPES = ['error_tracking_issue', 'logs_view', 'trace'] as const

export type TodayMonitorRecentType = (typeof TODAY_MONITOR_RECENT_TYPES)[number]

export interface TodayMonitorRecent {
    type: TodayMonitorRecentType
    name: string
    href: string
}

export const MONITOR_PANE: TodayProductPaneConfig = {
    pane: 'monitor',
    label: 'Monitor',
    lead: { id: 'tools', rowDataAttr: 'monitor-sidebar-tool', specs: monitorToolSpecs },
    sections: [{ id: 'products', label: 'AI', rowDataAttr: 'monitor-sidebar-product', specs: monitorAiProductSpecs }],
    recentTypes: TODAY_MONITOR_RECENT_TYPES,
}

export function isErrorTrackingIssuePath(path: string): boolean {
    return /^\/error-tracking\/[^/]+$/.test(path)
}
