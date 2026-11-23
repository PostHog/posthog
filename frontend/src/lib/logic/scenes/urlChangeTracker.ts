import { router } from 'kea-router'
import posthog from 'posthog-js'

/**
 * URL Change Tracking for Web Analytics Bug Investigation
 *
 * This module tracks URL changes in kea router to detect and diagnose rapid URL update cycles
 * that cause browser tab freezes. We've observed `[object Object]` appearing in URLs temporarily,
 * suggesting serialization issues that create infinite loops in the URL sync cycle.
 *
 * Owner: team-web-analytics
 * Context: https://github.com/PostHog/posthog/pull/49891
 *
 * Two detectors share this module:
 * - `trackUrlChange` sees writes that go through `trackedActionToUrl`, keyed per logic.
 * - `trackRouterLocationChange` sees every push and replace the router makes, whatever wrote it. It
 *   catches loops between logics, plain `actionToUrl` writes, and direct `router.actions.replace` calls.
 *
 * This is observability-only code - it does not suppress or modify URL updates,
 * only logs warnings and captures events when thresholds are exceeded.
 */

type ActionToUrlResponse = string | [string, Record<string, any>?, Record<string, any>?] | unknown

export function extractUrlString(response: ActionToUrlResponse): string | null {
    if (response === undefined || response === null) {
        return null
    }
    if (typeof response === 'string') {
        return response
    }
    if (Array.isArray(response)) {
        if (response.length === 0) {
            return null
        }
        // actionToUrl returns [pathname, searchParams?, hashParams?]
        // Serialize all parts to catch [object Object] in any component
        const parts: string[] = [String(response[0])]
        if (response[1] != null) {
            parts.push(`?${JSON.stringify(response[1])}`)
        }
        if (response[2] != null) {
            parts.push(`#${JSON.stringify(response[2])}`)
        }
        return parts.join('')
    }
    return String(response)
}

export function containsSerializationBug(url: string): boolean {
    return url.includes('[object Object]')
}

interface UrlChangeRecord {
    timestamp: number
    url: string
    logicPath: string
    actionName: string
}

interface UrlChangeTrackerConfig {
    maxChangesPerSecond: number
    windowMs: number
    throttleWarningMs: number
    loopBurstThreshold: number
}

const DEFAULT_CONFIG: UrlChangeTrackerConfig = {
    // A settling action<->URL round trip converges within a handful of writes, landing right around
    // 5-6 changes in the window. Keep the ceiling above that so ordinary sync churn isn't flagged;
    // only a burst that fails to converge (7+) looks like a genuine loop.
    maxChangesPerSecond: 6,
    windowMs: 3000,
    throttleWarningMs: 60000,
    // Above this many changes in the window we always treat the burst as a loop, even when every URL
    // is distinct. ~16 changes/sec sustained over the window is far beyond human typing but trivially
    // reached by a runaway router loop, so this catches loops that mutate the URL each iteration.
    loopBurstThreshold: 50,
}

class UrlChangeTracker {
    private changes: UrlChangeRecord[] = []
    private lastWarningTime: number = 0
    private config: UrlChangeTrackerConfig

    constructor(config: Partial<UrlChangeTrackerConfig> = {}) {
        this.config = { ...DEFAULT_CONFIG, ...config }
    }

    recordChange(url: string, logicPath: string, actionName: string): void {
        const now = Date.now()

        // Clean up old entries outside the window
        this.changes = this.changes.filter((c) => now - c.timestamp < this.config.windowMs)

        // Add new entry
        this.changes.push({ timestamp: now, url, logicPath, actionName })
    }

    isRapidlyChanging(): boolean {
        if (this.changes.length <= this.config.maxChangesPerSecond) {
            return false
        }
        // A runaway loop fires updates far faster and for longer than any human could, so an extreme
        // burst is always a loop - including one that mutates the URL each iteration (an incrementing
        // counter, timestamp, or re-serialized param) and so never repeats a URL.
        if (this.changes.length >= this.config.loopBurstThreshold) {
            return true
        }
        // Below that ceiling, a genuine loop re-sets the same handful of URLs over and over, so the
        // burst is dominated by duplicates. Legitimate rapid navigation - e.g. a user typing into a
        // search box that syncs each keystroke to the query string - produces a stream of mostly-distinct
        // URLs and must not be flagged as a loop. Only treat the burst as rapid when at most half of
        // the recorded changes are distinct URLs.
        const uniqueUrls = new Set(this.changes.map((c) => c.url)).size
        return uniqueUrls * 2 <= this.changes.length
    }

    canWarn(): boolean {
        return Date.now() - this.lastWarningTime >= this.config.throttleWarningMs
    }

    recordWarn(): void {
        this.lastWarningTime = Date.now()
    }

    getRecentChanges(): UrlChangeRecord[] {
        return [...this.changes]
    }

    getDebugInfo(): Record<string, unknown> {
        return {
            changeCount: this.changes.length,
            windowMs: this.config.windowMs,
            recentUrls: this.changes.slice(-5).map((c) => ({
                url: c.url.substring(0, 200),
                action: c.actionName,
                logic: c.logicPath,
            })),
        }
    }

    reset(): void {
        this.changes = []
        this.lastWarningTime = 0
    }
}

type UrlChangeDetector = 'action_to_url' | 'router'

const DETECTOR_ERRORS: Record<UrlChangeDetector, { message: string; tag: string; component: string }> = {
    action_to_url: {
        message: 'Rapid URL changes detected in kea router',
        tag: 'web_analytics_rapid_url_changes',
        component: 'tabAwareActionToUrl',
    },
    router: {
        message: 'Router URL loop detected',
        tag: 'router_rapid_url_changes',
        component: 'router',
    },
}

// The router logic's own path, so it can't collide with a logic tracked through `trackedActionToUrl`
const ROUTER_TRACKER_KEY = 'kea.router'

// The router tracker counts the writes of every mounted logic together, so a scene where a few logics
// each settle the URL once on load can pass the per-logic ceiling. A real loop writes dozens of times a
// second, so a higher ceiling still catches it within the first second.
const ROUTER_TRACKER_CONFIG: Partial<UrlChangeTrackerConfig> = { maxChangesPerSecond: 12 }

const trackersByLogicPath = new Map<string, UrlChangeTracker>()

export function getUrlChangeTracker(logicPath: string, config?: Partial<UrlChangeTrackerConfig>): UrlChangeTracker {
    if (!trackersByLogicPath.has(logicPath)) {
        trackersByLogicPath.set(logicPath, new UrlChangeTracker(config))
    }
    return trackersByLogicPath.get(logicPath)!
}

export function resetAllTrackers(): void {
    trackersByLogicPath.clear()
}

export function captureRapidUrlChangeWarning(
    tracker: UrlChangeTracker,
    currentUrl: string,
    logicPath: string,
    actionName: string,
    detector: UrlChangeDetector = 'action_to_url'
): void {
    if (!tracker.canWarn()) {
        return
    }
    tracker.recordWarn()

    const debugInfo = tracker.getDebugInfo()
    const sessionReplayUrl = posthog.get_session_replay_url?.({
        withTimestamp: true,
    })

    // Console warning for local debugging
    // eslint-disable-next-line no-console
    console.warn('[PostHog] Rapid URL changes detected - possible infinite loop', {
        currentUrl,
        logicPath,
        actionName,
        ...debugInfo,
        sessionReplayUrl,
    })

    // Capture exception to PostHog for monitoring. This runs synchronously inside the write that tripped
    // the detector, so the stack trace shows which code wrote the URL.
    const { message, tag, component } = DETECTOR_ERRORS[detector]
    const error = new Error(message)
    posthog.captureException(error, {
        tag,
        component,
        detector,
        severity: 'warning',
        url: currentUrl,
        logic_path: logicPath,
        action_name: actionName,
        change_count: debugInfo.changeCount,
        recent_urls: debugInfo.recentUrls,
        session_replay_url: sessionReplayUrl,
    })

    // Capture separate exception if serialization bug is present
    if (containsSerializationBug(currentUrl)) {
        posthog.captureException(new Error('URL contains [object Object] - serialization bug'), {
            tag: 'web_analytics_url_serialization_bug',
            url: currentUrl,
            logic_path: logicPath,
            action_name: actionName,
        })
    }

    // Capture as event for easier querying/alerting
    posthog.capture('kea_router_rapid_url_changes', {
        detector,
        url: currentUrl,
        logic_path: logicPath,
        action_name: actionName,
        change_count: debugInfo.changeCount,
        recent_urls: debugInfo.recentUrls,
        has_object_object: containsSerializationBug(currentUrl),
        session_replay_url: sessionReplayUrl,
    })
}

export function trackUrlChange(response: ActionToUrlResponse, logicPath: string, actionName: string): void {
    // The rapid-change threshold assumes human pacing in a real browser; jest tests
    // legitimately navigate many times per second, so the heuristic can only false-positive there.
    if (process.env.NODE_ENV === 'test') {
        return
    }
    try {
        const urlString = extractUrlString(response)
        if (urlString === null) {
            return
        }

        const tracker = getUrlChangeTracker(logicPath)

        if (containsSerializationBug(urlString)) {
            // eslint-disable-next-line no-console
            console.error('[PostHog] Invalid URL detected - contains [object Object]', {
                url: urlString,
                action: actionName,
                logic: logicPath,
            })
        }

        tracker.recordChange(urlString, logicPath, actionName)

        if (tracker.isRapidlyChanging()) {
            captureRapidUrlChangeWarning(tracker, urlString, logicPath, actionName)
        }
    } catch {
        // Silently ignore errors - this is observability code that should never disturb the app
    }
}

export function trackRouterLocationChange(method: string, url: string): void {
    // Back and forward come from the person, not from code, so they can't be a write loop
    if (method === 'POP') {
        return
    }
    try {
        const tracker = getUrlChangeTracker(ROUTER_TRACKER_KEY, ROUTER_TRACKER_CONFIG)
        tracker.recordChange(url, ROUTER_TRACKER_KEY, method)
        if (tracker.isRapidlyChanging()) {
            captureRapidUrlChangeWarning(tracker, url, ROUTER_TRACKER_KEY, method, 'router')
        }
    } catch {
        // Silently ignore errors - this is observability code that should never disturb the app
    }
}

type RouterAction = { type?: string; payload?: { method?: string; url?: string; initial?: boolean } }

/** Redux middleware that feeds every router location change to `trackRouterLocationChange`. */
export const routerUrlChangeTrackingMiddleware =
    () =>
    (next: (action: unknown) => unknown) =>
    (action: unknown): unknown => {
        // Same reason as in `trackUrlChange`: jest navigates many times per second
        if (process.env.NODE_ENV !== 'test') {
            try {
                const { type, payload } = (action ?? {}) as RouterAction
                if (type === router.actionTypes.locationChanged && payload?.url && !payload.initial) {
                    trackRouterLocationChange(payload.method ?? '', payload.url)
                }
            } catch {
                // Silently ignore errors - this is observability code that should never disturb the app
            }
        }
        return next(action)
    }

export { UrlChangeTracker }
