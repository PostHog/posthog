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
}

const DEFAULT_CONFIG: UrlChangeTrackerConfig = {
    maxChangesPerSecond: 4,
    windowMs: 3000,
    throttleWarningMs: 60000,
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
        return this.changes.length > this.config.maxChangesPerSecond
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

const trackersByLogicPath = new Map<string, UrlChangeTracker>()

export function getUrlChangeTracker(logicPath: string): UrlChangeTracker {
    if (!trackersByLogicPath.has(logicPath)) {
        trackersByLogicPath.set(logicPath, new UrlChangeTracker())
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
    actionName: string
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

    // Capture exception to PostHog for monitoring
    const error = new Error('Rapid URL changes detected in kea router')
    posthog.captureException(error, {
        tag: 'web_analytics_rapid_url_changes',
        component: 'tabAwareActionToUrl',
        severity: 'warning',
        url: currentUrl,
        logic_path: logicPath,
        action_name: actionName,
        change_count: debugInfo.changeCount,
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
        url: currentUrl,
        logic_path: logicPath,
        action_name: actionName,
        change_count: debugInfo.changeCount,
        has_object_object: containsSerializationBug(currentUrl),
        session_replay_url: sessionReplayUrl,
    })
}

export function trackUrlChange(response: ActionToUrlResponse, logicPath: string, actionName: string): void {
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

export { UrlChangeTracker }
