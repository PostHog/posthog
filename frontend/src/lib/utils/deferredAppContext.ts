import type { AppContext } from '~/types'

import { markBootPhase } from './bootTiming'

// pinned: query param read by `defers_user_app_context` in posthog/utils.py
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

// The keys `add_user_app_context` in posthog/utils.py fills. A deferred page gets them only from `/_app_context`.
const USER_APP_CONTEXT_KEYS = new Set([
    'current_user',
    'current_team',
    'current_project',
    'effective_resource_access_control',
    'resource_access_control',
    'default_event_name',
    'has_pageview',
    'has_screen',
    'has_person_email',
    'homepage',
])

let earlyReads: Set<string> | undefined
let userDataArrived = false

/**
 * Records each user data key that code reads before the data arrives, when it is still missing.
 * The boot timing event reports the keys, so a read like that shows up in production.
 */
export function watchEarlyUserContextReads(): void {
    const context = window.POSTHOG_APP_CONTEXT
    if (!window.POSTHOG_APP_CONTEXT_REQUEST || !context) {
        return
    }
    const reads = new Set<string>()
    earlyReads = reads
    userDataArrived = false
    window.POSTHOG_APP_CONTEXT = new Proxy(context, {
        get(target, key, receiver) {
            if (!userDataArrived && typeof key === 'string' && USER_APP_CONTEXT_KEYS.has(key)) {
                reads.add(key)
            }
            return Reflect.get(target, key, receiver)
        },
    })
}

export function earlyUserContextReads(): string[] {
    return [...(earlyReads ?? [])]
}

export function inlineAppContextUrl(href: string): string {
    const url = new URL(href)
    url.searchParams.set(DEFERRED_APP_CONTEXT_PARAM, '0')
    return url.toString()
}

/**
 * Adds the user's data to the app context when the page left it out. The app must not boot before this resolves.
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
    // Merge in place, so code that kept the context object before the data arrived also gets the data.
    window.POSTHOG_APP_CONTEXT = Object.assign(window.POSTHOG_APP_CONTEXT ?? {}, deferred.app_context) as AppContext
    userDataArrived = true
    window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
        ...window.POSTHOG_USER_IDENTITY_WITH_FLAGS,
        featureFlags: deferred.feature_flags,
    }
    markBootPhase('app_context_loaded', { early_user_context_reads: earlyUserContextReads() })
}
