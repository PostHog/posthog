import { toolbarPosthogJS } from '~/toolbar/shared/toolbarPosthogJS'

// pinned: sent as the `tool` property of `toolbar extension page tool used`
type PageToolKey =
    | 'heatmap'
    | 'inspect'
    | 'save-heatmap'
    | 'actions'
    | 'create-action'
    | 'save-action'
    | 'flags'
    | 'override-flag'
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
