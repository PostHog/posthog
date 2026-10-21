import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'

// pinned: sent as the `tool` property of `toolbar extension page tool used`
type PageToolKey = 'heatmap' | 'inspect' | 'save-heatmap'

export function capturePageToolUsed(tool: PageToolKey, properties?: Record<string, unknown>): void {
    // pinned: analytics event name
    toolbarPosthogJS.capture('toolbar extension page tool used', { tool, ...properties })
}
