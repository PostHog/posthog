import posthog from 'posthog-js'

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
    maxChangesPerSecond: 5,
    windowMs: 1000,
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
    const sessionReplayUrl = posthog.get_session_replay_url?.({ withTimestamp: true })

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
        tags: {
            component: 'tabAwareActionToUrl',
            severity: 'warning',
        },
        extra: {
            currentUrl: currentUrl.substring(0, 500),
            logicPath,
            actionName,
            ...debugInfo,
            sessionReplayUrl,
        },
    })

    // Capture as event for easier querying/alerting
    posthog.capture('kea_router_rapid_url_changes', {
        url: currentUrl.substring(0, 500),
        logic_path: logicPath,
        action_name: actionName,
        change_count: debugInfo.changeCount,
        has_object_object: currentUrl.includes('[object Object]'),
        session_replay_url: sessionReplayUrl,
    })
}

export { UrlChangeTracker }
