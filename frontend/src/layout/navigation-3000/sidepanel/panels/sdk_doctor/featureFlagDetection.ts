/* oxlint-disable no-console */
import type { EventType } from '~/types'

export type FeatureFlagMisconfiguration = {
    detected: boolean
    detectedAt: string
    flagsCalledBeforeLoading: string[]
    exampleEventId?: string
    exampleEventTimestamp?: string
    flagExampleEvents: Record<string, { eventId: string; timestamp: string }>
    sessionCount: number
}

/**
 * Detects if running in demo/dev mode based on URL patterns.
 * Used to apply additional event filtering in development.
 */
export function isDemoMode(): boolean {
    const url = window.location.href
    return (
        url.includes('localhost') ||
        url.includes('127.0.0.1') ||
        url.includes('demo') ||
        url.includes(':8000') ||
        url.includes(':8010')
    ) // PostHog dev server
}

/**
 * Analyzes recent events to detect feature flag timing issues.
 *
 * Uses contextual thresholds based on initialization patterns:
 * - 0ms threshold when bootstrap detected (flags available immediately)
 * - 350ms threshold when proper init patterns detected (FOUC prevention friendly)
 * - 500ms threshold for default/unmitigated cases (catches race conditions)
 *
 * Also detects when timing issues are resolved and cleans up stale detections.
 *
 * @param currentState - Current feature flag misconfiguration state
 * @param recentEvents - Array of recent events from PostHog
 * @param isDebugMode - Whether debug logging is enabled
 * @returns Updated FeatureFlagMisconfiguration state
 */
export function detectFeatureFlagMisconfiguration(
    currentState: FeatureFlagMisconfiguration,
    recentEvents: EventType[],
    isDebugMode: boolean
): FeatureFlagMisconfiguration {
    // Only look at recent events to avoid cross-contamination
    const tenMinutesAgo = Date.now() - 10 * 60 * 1000
    const limitedEvents = recentEvents.slice(0, 15)

    // Filter out PostHog's internal UI events (URLs containing /project/1/)
    // In dev mode, also filter out test@posthog.com events (dev UI interactions)
    const customerEvents = limitedEvents.filter(
        (event) =>
            !event.properties?.$current_url?.includes('/project/1') &&
            !(
                isDemoMode() &&
                (event.properties?.email === 'test@posthog.com' || event.distinct_id === 'test@posthog.com')
            )
    )

    // Filter for web events from the last 10 minutes
    const webEvents = customerEvents
        .filter(
            (event) =>
                event.properties?.$lib === 'web' &&
                event.properties?.$session_id &&
                new Date(event.timestamp).getTime() > tenMinutesAgo
        )
        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

    if (webEvents.length === 0) {
        // Clean up feature flag detection when no web events present
        // This prevents stale detections from persisting when all events are filtered
        if (currentState.detected) {
            return {
                detected: false,
                detectedAt: '',
                flagsCalledBeforeLoading: [],
                flagExampleEvents: {},
                sessionCount: 0,
            }
        }
        return currentState
    }

    // Group ALL events by session ID for session-based analysis
    const sessionEventMap: Record<string, typeof webEvents> = {}
    webEvents.forEach((event) => {
        const sessionId = event.properties?.$session_id
        if (sessionId) {
            if (!sessionEventMap[sessionId]) {
                sessionEventMap[sessionId] = []
            }
            sessionEventMap[sessionId].push(event)
        }
    })

    const problematicFlags = new Set<string>()
    let exampleEventId: string | undefined
    let exampleEventTimestamp: string | undefined
    const flagExampleEvents: Record<string, { eventId: string; timestamp: string }> = {}
    const uniqueSessions = new Set<string>()

    // Analyze each session for flag timing issues
    Object.entries(sessionEventMap).forEach(([sessionId, sessionEvents]) => {
        if (sessionEvents.length === 0) {
            return
        }

        uniqueSessions.add(sessionId)

        // Sort events by timestamp within this session
        const sortedEvents = sessionEvents.sort(
            (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
        )

        console.info(
            `[SDK Doctor Debug] Session events:`,
            sortedEvents.map((e) => ({
                event: e.event,
                timestamp: e.timestamp,
                flag: e.properties?.$feature_flag,
                bootstrapped: e.properties?.$feature_flag_bootstrapped,
            }))
        )

        // Find the first event of any type as baseline (SDK initialization baseline)
        const firstEvent = sortedEvents[0]
        const firstEventTime = new Date(firstEvent.timestamp).getTime()

        console.info(
            `[SDK Doctor Debug] First event: ${firstEvent.event} at ${firstEvent.timestamp} (${firstEventTime})`
        )

        // Get flag events in this session
        const flagEvents = sortedEvents.filter((event) => event.event === '$feature_flag_called')

        if (flagEvents.length === 0) {
            return
        }

        // Detect bootstrap state for contextual thresholds
        const hasBootstrap = sortedEvents.some((event) => event.properties?.$feature_flag_bootstrapped === true)

        // Detect proper init patterns (e.g., presence of specific ready events)
        const hasProperInitPattern = sortedEvents.some(
            (event) => event.event === '$pageview' || event.event === '$identify' || event.properties?.$device_type // Common indicators of proper initialization
        )

        // Contextual threshold system based on mitigation patterns
        let threshold: number
        if (hasBootstrap) {
            threshold = 0 // Bootstrap detected: no timing restrictions
        } else if (hasProperInitPattern) {
            threshold = 350 // FOUC prevention friendly, reduces false positives
        } else {
            threshold = 500 // Default/unmitigated: catches race conditions
        }

        console.info(
            `[SDK Doctor Debug] Session analysis - Bootstrap: ${hasBootstrap}, ProperInit: ${hasProperInitPattern}, Threshold: ${threshold}ms`
        )

        // Check each flag event for timing issues
        flagEvents.forEach((flagEvent) => {
            const flagTime = new Date(flagEvent.timestamp).getTime()
            const timeDiff = flagTime - firstEventTime

            console.info(`[SDK Doctor Debug]   - Bootstrapped: ${flagEvent.properties?.$feature_flag_bootstrapped}`)

            // Enhanced timing logic: flagTime < firstEventTime OR (timeDiff >= 0 AND timeDiff < threshold)
            const isProblematic = flagTime < firstEventTime || (timeDiff >= 0 && timeDiff < threshold)

            console.info(
                `[SDK Doctor Debug]   - Is problematic: ${isProblematic} (${timeDiff}ms < ${threshold}ms threshold)`
            )

            if (isProblematic) {
                const flagName = flagEvent.properties?.$feature_flag
                if (flagName && flagEvent.id) {
                    problematicFlags.add(flagName)

                    // Capture per-flag example events (only first occurrence per flag)
                    if (!flagExampleEvents[flagName]) {
                        flagExampleEvents[flagName] = {
                            eventId: flagEvent.id,
                            timestamp: flagEvent.timestamp,
                        }
                    }

                    // Capture first global example for backwards compatibility
                    if (!exampleEventId) {
                        exampleEventId = flagEvent.id
                        exampleEventTimestamp = flagEvent.timestamp
                    }

                    console.warn(
                        `[SDK Doctor] Flag timing issue detected: ${flagName} called ${timeDiff}ms after init (threshold: ${threshold}ms, bootstrap: ${hasBootstrap})`
                    )
                }
            }
        })
    })

    // If we detect new problems, update state
    if (problematicFlags.size > 0) {
        return {
            detected: true,
            detectedAt: currentState.detectedAt || new Date().toISOString(),
            flagsCalledBeforeLoading: Array.from(
                new Set([...currentState.flagsCalledBeforeLoading, ...Array.from(problematicFlags)])
            ),
            exampleEventId: exampleEventId || currentState.exampleEventId,
            exampleEventTimestamp: exampleEventTimestamp || currentState.exampleEventTimestamp,
            flagExampleEvents: { ...currentState.flagExampleEvents, ...flagExampleEvents },
            sessionCount: Math.max(uniqueSessions.size, currentState.sessionCount),
        }
    }

    // Enhanced resolution detection: Check recent flag events for improved timing patterns
    if (currentState.detected) {
        const recentFlagEvents = webEvents.filter((event) => event.event === '$feature_flag_called').slice(-5) // Last 5 flag events

        if (recentFlagEvents.length >= 2) {
            // Check if recent flag events demonstrate proper timing patterns
            const hasImprovedTiming = recentFlagEvents.every((flagEvent) => {
                const sessionId = flagEvent.properties?.$session_id
                const sessionEvents = sessionEventMap[sessionId] || []

                if (sessionEvents.length === 0) {
                    return false
                }

                const firstEvent = sessionEvents.sort(
                    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
                )[0]
                const firstEventTime = new Date(firstEvent.timestamp).getTime()
                const flagTime = new Date(flagEvent.timestamp).getTime()
                const timeDiff = flagTime - firstEventTime

                // Check if timing is now acceptable (using same contextual thresholds)
                const hasBootstrap = sessionEvents.some(
                    (event) => event.properties?.$feature_flag_bootstrapped === true
                )
                const hasProperInitPattern = sessionEvents.some(
                    (event) =>
                        event.event === '$pageview' || event.event === '$identify' || event.properties?.$device_type
                )

                let threshold: number
                if (hasBootstrap) {
                    threshold = 0
                } else if (hasProperInitPattern) {
                    threshold = 350
                } else {
                    threshold = 500
                }

                return flagTime >= firstEventTime && timeDiff >= threshold
            })

            if (hasImprovedTiming && problematicFlags.size === 0) {
                if (isDebugMode) {
                    console.info('[SDK Doctor] Flag timing has improved - clearing detection state')
                }
                return {
                    detected: false,
                    detectedAt: '',
                    flagsCalledBeforeLoading: [],
                    flagExampleEvents: {},
                    sessionCount: 0,
                }
            }
        }
    }

    return currentState
}
