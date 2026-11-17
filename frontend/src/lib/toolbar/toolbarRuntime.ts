import type { PostHog } from 'posthog-js/dist/module'

import type { ToolbarProject } from './toolbarProject'

// App modules import this file, so it must not import any toolbar module or the toolbar ships on every app page.

export interface ToolbarRuntime {
    uiHost: () => string
    posthog: () => PostHog | null
    isAuthenticated: () => boolean
    authenticate: () => void
    project: () => ToolbarProject | null
}

let mountedRuntime: ToolbarRuntime | null = null

export function registerToolbarRuntime(runtime: ToolbarRuntime): () => void {
    mountedRuntime = runtime
    return () => {
        if (mountedRuntime === runtime) {
            mountedRuntime = null
        }
    }
}

/** The mounted toolbar, or null when the code runs in the PostHog app. */
export function getToolbarRuntime(): ToolbarRuntime | null {
    return mountedRuntime
}
