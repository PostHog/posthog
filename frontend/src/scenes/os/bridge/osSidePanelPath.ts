import { urls } from 'scenes/urls'

import { SidePanelTab } from '~/types'

/**
 * The app path that shows what a side panel tab would show, or null when no page does. Support is null
 * because a window opens the support form itself.
 */
export function osSidePanelPath(tab: string, options?: string): string | null {
    switch (tab) {
        case SidePanelTab.Max:
            // A `!` prefix asks PostHog AI to send the prompt, and the AI page does the same for `ask`.
            return options?.startsWith('!') && options.length > 1 ? urls.ai(undefined, options.slice(1)) : urls.ai()
        case SidePanelTab.Activity:
            return urls.advancedActivityLogs()
        case SidePanelTab.Notebooks:
            return options && /^[\w-]+$/.test(options) ? urls.notebook(options) : urls.notebooks()
        case SidePanelTab.Exports:
            return urls.exports()
        default:
            return null
    }
}
