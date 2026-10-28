import type { AppContext } from '~/types'

import { markBootPhase } from './bootTiming'

// pinned: query param read by `deferred_app_context_variant` in posthog/utils.py
const DEFERRED_APP_CONTEXT_PARAM = 'deferred_app_context'

interface DeferredAppContext {
    app_context: Partial<AppContext>
    feature_flags: Record<string, boolean | string> | null
}

declare global {
    interface Window {
        /** Set by the page when it leaves the user's data out of the app context. See head.html. */
        POSTHOG_APP_CONTEXT_REQUEST?: Promise<DeferredAppContext>
    }
}

export function inlineAppContextUrl(href: string): string {
    const url = new URL(href)
    url.searchParams.set(DEFERRED_APP_CONTEXT_PARAM, '0')
    return url.toString()
}

/**
 * Adds the user's data to the app context when the page left it out. Code that reads the app context
 * when its module loads must not load before this resolves.
 */
export async function applyDeferredAppContext(): Promise<void> {
    const request = window.POSTHOG_APP_CONTEXT_REQUEST
    if (!request) {
        return
    }
    let deferred: DeferredAppContext
    try {
        deferred = await request
    } catch {
        window.location.replace(inlineAppContextUrl(window.location.href))
        // The page is going away, so never let the boot continue without the user's data.
        return new Promise(() => {})
    }
    window.POSTHOG_APP_CONTEXT = { ...window.POSTHOG_APP_CONTEXT, ...deferred.app_context } as AppContext
    window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
        ...window.POSTHOG_USER_IDENTITY_WITH_FLAGS,
        featureFlags: deferred.feature_flags,
    }
    markBootPhase('app_context_loaded')
}
