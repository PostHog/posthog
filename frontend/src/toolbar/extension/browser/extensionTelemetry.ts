import { toolbarPosthogJS } from '~/toolbar/shared/toolbarPosthogJS'

// pinned: sent as the `tool` property of `toolbar extension page tool used`
type PageToolKey =
    | 'heatmap'
    | 'inspect'
    | 'save-heatmap'
    | 'heatmap-variant-filter'
    | 'actions'
    | 'create-action'
    | 'save-action'
    | 'flags'
    | 'override-flag'
    | 'compare-flag'
    | 'clear-flag-overrides'
    | 'impersonate-flags'
    | 'events'
    | 'export-events'
    | 'web-vitals'
    | 'experiments'
    | 'create-experiment'
    | 'save-experiment'
    | 'more'
    | 'pii-masking'
    | 'screenshot-for-event'
    | 'view-session-recording'

export function capturePageToolUsed(tool: PageToolKey, properties?: Record<string, unknown>): void {
    // pinned: analytics event name
    toolbarPosthogJS.capture('toolbar extension page tool used', { tool, ...properties })
}

// pinned: analytics event names, which flagComparisonLogic sends from the floating toolbar too
const FLAG_COMPARISON_EVENTS = {
    started: 'toolbar feature flag comparison started',
    completed: 'toolbar feature flag comparison completed',
    failed: 'toolbar feature flag comparison failed',
} as const

/** The page's copy of the toolbar's posthog-js never sends, so the panel reports the comparison the page ran. */
export function captureFlagComparison(
    stage: keyof typeof FLAG_COMPARISON_EVENTS,
    properties: Record<string, unknown>
): void {
    toolbarPosthogJS.capture(FLAG_COMPARISON_EVENTS[stage], { ...properties, source: 'extension' })
}
