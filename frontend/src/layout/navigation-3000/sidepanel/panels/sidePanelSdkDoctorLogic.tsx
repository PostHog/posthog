import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { isNotNil } from 'lib/utils'
import { diffVersions, parseVersion, tryParseVersion } from 'lib/utils/semver'
import { teamLogic } from 'scenes/teamLogic'

import { EventsListQueryParams, EventType } from '~/types'

import type { sidePanelSdkDoctorLogicType } from './sidePanelSdkDoctorLogicType'

// Global cache for GitHub releases data
let releasesCache: { data: any[] | null; timestamp: number } = { data: null, timestamp: 0 }

// Helper function to check if version difference suggests multiple inits vs auto-update
function isSignificantVersionGap(version1: string | undefined, version2: string | undefined): boolean {
    if (!version1 || !version2) {
        return true
    } // Unknown versions = assume problem
    if (version1 === version2) {
        return false
    } // Same version = not multiple inits

    // Primary method: Check actual release dates using cached data
    if (releasesCache.data) {
        const releaseGap = checkReleaseTimeGapFromCache(version1, version2, releasesCache.data)
        if (releaseGap !== null) {
            // const daysDiff = releaseGap / (24 * 60 * 60 * 1000)
            // console.log(`[SDK Doctor] GitHub API: ${version1} vs ${version2} = ${daysDiff.toFixed(1)} days apart`)
            // If releases are >4 days apart, likely multiple inits (not auto-update)
            return releaseGap > 4 * 24 * 60 * 60 * 1000 // 4 days in milliseconds
        }
        // console.log(`[SDK Doctor] GitHub API: Could not find releases for ${version1} or ${version2}, falling back to heuristic`)
    } else {
        // console.log('[SDK Doctor] GitHub API: No cache data available, falling back to heuristic')
    }

    // Fallback method: Simple version number heuristic
    try {
        // Parse semantic versions (e.g., "1.255.0")
        const parseVersion = (v: string): { major: number; minor: number; patch: number } => {
            const parts = v.split('.').map(Number)
            return { major: parts[0] || 0, minor: parts[1] || 0, patch: parts[2] || 0 }
        }

        const v1 = parseVersion(version1)
        const v2 = parseVersion(version2)

        // Different major versions = definitely multiple inits
        if (v1.major !== v2.major) {
            return true
        }

        // Minor version difference of 3+ = likely multiple inits (not auto-update)
        const minorDiff = Math.abs(v1.minor - v2.minor)
        // console.log(`[SDK Doctor] Heuristic: ${version1} vs ${version2} = ${minorDiff} minor versions apart`)

        if (minorDiff >= 3) {
            // console.log(`[SDK Doctor] Heuristic: ${minorDiff} >= 3, detecting as multiple inits`)
            return true
        }

        // Small version differences = likely auto-update, not multiple inits
        // console.log(`[SDK Doctor] Heuristic: ${minorDiff} < 3, treating as auto-update`)
        return false
    } catch (e) {
        // If we can't parse versions, assume it's a problem to be safe
        return true
    }
}

// Check time gap between two releases using cached data
function checkReleaseTimeGapFromCache(version1: string, version2: string, releases: any[]): number | null {
    try {
        // Find the two versions in the releases - try multiple matching strategies
        const findRelease = (version: string): any => {
            return releases.find(
                (r: any) =>
                    r.tag_name === `v${version}` || // Exact match with v prefix
                    r.tag_name === version || // Exact match without prefix
                    r.tag_name.includes(version) || // Contains version
                    r.name?.includes(version) // Check release name too
            )
        }

        const release1 = findRelease(version1)
        const release2 = findRelease(version2)

        if (!release1 || !release2) {
            return null
        }

        // Calculate time difference
        const date1 = new Date(release1.published_at).getTime()
        const date2 = new Date(release2.published_at).getTime()

        return Math.abs(date1 - date2)
    } catch (error) {
        return null
    }
}

// Fetch and cache GitHub releases data
async function updateReleasesCache(): Promise<void> {
    try {
        // Check if cache is still fresh (30 minutes)
        const now = Date.now()
        const cacheAge = now - releasesCache.timestamp
        const thirtyMinutes = 30 * 60 * 1000

        if (releasesCache.data && cacheAge < thirtyMinutes) {
            return // Cache still fresh
        }

        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 1500) // 1.5s timeout

        const response = await fetch('https://api.github.com/repos/PostHog/posthog-js/releases?per_page=100', {
            signal: controller.signal,
            headers: {
                Accept: 'application/vnd.github.v3+json',
                'User-Agent': 'PostHog-SDK-Doctor',
            },
        })

        clearTimeout(timeoutId)

        if (response.ok) {
            const releases = await response.json()
            releasesCache = { data: releases, timestamp: now }
        }
    } catch (error) {
        // Keep existing cache or leave empty - fallback will handle it
        // console.log('[SDK Doctor] Failed to update releases cache, using fallback method')
    }
}

// Helper function to check if version difference indicates outdated SDK (different threshold than multiple inits)
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function isOutdatedVersionGap(version1: string | undefined, version2: string | undefined): boolean {
    if (!version1 || !version2) {
        return true
    } // Unknown versions = assume outdated
    if (version1 === version2) {
        return false
    } // Same version = not outdated

    // For outdated detection, use cached GitHub API data if available
    if (releasesCache.data) {
        const releaseGap = checkReleaseTimeGapFromCache(version1, version2, releasesCache.data)
        if (releaseGap !== null) {
            // const daysDiff = releaseGap / (24 * 60 * 60 * 1000)
            // console.log(`[SDK Doctor] Outdated check: ${version1} vs ${version2} = ${daysDiff.toFixed(1)} days apart`)
            // If releases are >7 days apart, likely outdated SDK (more lenient than multiple init detection)
            return releaseGap > 7 * 24 * 60 * 60 * 1000 // 7 days in milliseconds
        }
        // console.log(`[SDK Doctor] Outdated check: Could not find releases for ${version1} or ${version2}, falling back to heuristic`)
    }

    // Fallback: Consider "more than two releases apart" as outdated
    try {
        const parseVersion = (v: string): { major: number; minor: number; patch: number } => {
            const parts = v.split('.').map(Number)
            return { major: parts[0] || 0, minor: parts[1] || 0, patch: parts[2] || 0 }
        }

        const v1 = parseVersion(version1)
        const v2 = parseVersion(version2)

        // Different major versions = definitely outdated
        if (v1.major !== v2.major) {
            return true
        }

        // Minor version difference of 2+ = likely outdated SDK
        const minorDiff = Math.abs(v1.minor - v2.minor)
        // console.log(`[SDK Doctor] Outdated heuristic: ${version1} vs ${version2} = ${minorDiff} minor versions apart`)

        if (minorDiff >= 2) {
            // console.log(`[SDK Doctor] Outdated heuristic: ${minorDiff} >= 2, considering outdated`)
            return true
        }

        // console.log(`[SDK Doctor] Outdated heuristic: ${minorDiff} < 2, considering current`)
        return false
    } catch (e) {
        return true // If we can't parse versions, assume outdated to be safe
    }
}

export type SdkType =
    | 'web'
    | 'ios'
    | 'android'
    | 'node'
    | 'python'
    | 'php'
    | 'ruby'
    | 'go'
    | 'flutter'
    | 'react-native'
    | 'other'
export type SdkVersionInfo = {
    type: SdkType
    version: string
    isOutdated: boolean
    count: number
    releasesAhead?: number
    latestVersion?: string
    multipleInitializations?: boolean
    initCount?: number
    initUrls?: { url: string; count: number }[] // Add this to track actual URLs
}

export type MultipleInitDetection = {
    detected: boolean
    detectedAt: string // timestamp when first detected
    exampleEventId?: string // UUID of a problematic event
    exampleEventTimestamp?: string // timestamp of the problematic event
    affectedUrls: string[]
    sessionCount: number
}

export type FeatureFlagMisconfiguration = {
    detected: boolean
    detectedAt: string // timestamp when first detected
    flagsCalledBeforeLoading: string[] // list of flags called before ready
    exampleEventId?: string // UUID of a problematic event
    exampleEventTimestamp?: string // timestamp of the problematic event
    sessionCount: number
}

export type SdkHealthStatus = 'healthy' | 'warning' | 'critical'

// Add a cache utility for GitHub API responses
const GITHUB_CACHE_KEY = 'posthog_sdk_versions_cache'
const GITHUB_CACHE_EXPIRY = 24 * 60 * 60 * 1000 // 24 hours in milliseconds

interface GitHubCache {
    timestamp: number
    data: Record<SdkType, { latestVersion: string; versions: string[] }>
}

// Utility functions for the GitHub API cache
const getGitHubCache = (): GitHubCache | null => {
    try {
        const cachedData = localStorage.getItem(GITHUB_CACHE_KEY)
        if (!cachedData) {
            return null
        }

        const parsedCache = JSON.parse(cachedData) as GitHubCache
        const now = Date.now()

        // Check if cache is expired
        if (now - parsedCache.timestamp > GITHUB_CACHE_EXPIRY) {
            localStorage.removeItem(GITHUB_CACHE_KEY)
            return null
        }

        return parsedCache
    } catch {
        // console.error('[SDK Doctor] Error reading GitHub cache:', error)
        localStorage.removeItem(GITHUB_CACHE_KEY)
        return null
    }
}

const setGitHubCache = (data: Record<SdkType, { latestVersion: string; versions: string[] }>): void => {
    try {
        const cacheData: GitHubCache = {
            timestamp: Date.now(),
            data,
        }
        localStorage.setItem(GITHUB_CACHE_KEY, JSON.stringify(cacheData))
    } catch {
        // console.error('[SDK Doctor] Error saving GitHub cache:', error)
    }
}

export const sidePanelSdkDoctorLogic = kea<sidePanelSdkDoctorLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSdkDoctorLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadRecentEvents: true,
        loadLatestSdkVersions: true,
    }),

    loaders(({ values }) => ({
        recentEvents: [
            [] as EventType[],
            {
                loadRecentEvents: async () => {
                    // Force a fresh reload of events
                    const params: EventsListQueryParams = {
                        limit: 15,
                        orderBy: ['-timestamp'],
                        after: '-24h',
                    }
                    // Use a default team ID if currentTeamId is null
                    const teamId = values.currentTeamId || undefined
                    try {
                        const response = await api.events.list(params, 15, teamId)
                        return response.results
                    } catch (error) {
                        console.error('Error loading events:', error)
                        return values.recentEvents || [] // Return existing data on error
                    }
                },
            },
        ],

        // Fetch latest SDK versions from GitHub API
        latestSdkVersions: [
            {} as Record<SdkType, { latestVersion: string; versions: string[] }>,
            {
                loadLatestSdkVersions: async () => {
                    // console.log('[SDK Doctor] Loading latest SDK versions')

                    // Check cache first
                    const cachedData = getGitHubCache()
                    if (cachedData) {
                        // console.log('[SDK Doctor] Using cached GitHub data')
                        return cachedData.data
                    }

                    // console.log('[SDK Doctor] No valid cache found, fetching from GitHub API')

                    // Map SDK types to their GitHub repositories
                    const sdkRepoMap: Record<SdkType, { repo: string; versionPrefix?: string; subdirectory?: string }> =
                        {
                            web: { repo: 'posthog-js' },
                            ios: { repo: 'posthog-ios' },
                            android: { repo: 'posthog-android' },
                            node: { repo: 'posthog-js-lite', subdirectory: 'posthog-node' },
                            python: { repo: 'posthog-python' },
                            php: { repo: 'posthog-php' },
                            ruby: { repo: 'posthog-ruby' },
                            go: { repo: 'posthog-go' },
                            flutter: { repo: 'posthog-flutter' },
                            'react-native': { repo: 'posthog-react-native' },
                            other: { repo: '' }, // Skip for "other"
                        }

                    const result: Record<SdkType, { latestVersion: string; versions: string[] }> = {} as Record<
                        SdkType,
                        { latestVersion: string; versions: string[] }
                    >

                    // Create an array of promises for each SDK type
                    const promises = Object.entries(sdkRepoMap)
                        .filter(([_, { repo }]) => !!repo) // Skip entries with empty repos
                        .map(async ([sdkType, { repo }]) => {
                            try {
                                // Using the same approach as versionCheckerLogic
                                // For Node.js SDK we need special handling since it's in a subdirectory of posthog-js-lite
                                const isNodeSdk = sdkType === 'node'

                                // Add cache busting parameter to avoid GitHub's aggressive caching
                                const cacheBuster = Date.now()
                                const tagsPromise = fetch(
                                    `https://api.github.com/repos/PostHog/${repo}/tags?_=${cacheBuster}`,
                                    {
                                        headers: {
                                            Accept: 'application/vnd.github.v3+json',
                                        },
                                    }
                                )
                                    .then((r) => {
                                        // Check for rate limiting
                                        if (r.status === 403) {
                                            // console.error(`[SDK Doctor] GitHub API rate limit hit for ${sdkType}`)
                                            throw new Error('GitHub API rate limit exceeded')
                                        }
                                        return r.json()
                                    })
                                    .then((tags) => {
                                        if (tags && Array.isArray(tags) && tags.length > 0) {
                                            // Extract versions from tags
                                            const versions = tags
                                                .map((tag: any) => {
                                                    const name = tag.name.replace(/^v/, '')
                                                    // For Node.js SDK, only consider tags with the "node-" prefix
                                                    if (isNodeSdk) {
                                                        if (tag.name.startsWith('node-')) {
                                                            // Remove the "node-" prefix for comparison
                                                            const nodeVersion = tag.name.replace(/^node-/, '')
                                                            return tryParseVersion(nodeVersion) ? nodeVersion : null
                                                        }
                                                        return null
                                                    }
                                                    return tryParseVersion(name) ? name : null
                                                })
                                                .filter(isNotNil)

                                            if (versions.length > 0) {
                                                return {
                                                    sdkType,
                                                    versions: versions,
                                                    latestVersion: versions[0],
                                                }
                                            }
                                        }
                                        return null
                                    })
                                    .catch(() => {
                                        // console.error(`Error fetching latest version for ${sdkType}:`, error)
                                        return null
                                    })

                                return tagsPromise
                            } catch {
                                // console.error(`Error setting up fetch for ${sdkType}:`, error)
                                return null
                            }
                        })

                    // Wait for all promises to settle and process results
                    const settled = await Promise.allSettled(promises)

                    // Process successful results
                    settled.forEach((settlement) => {
                        if (settlement.status === 'fulfilled' && settlement.value) {
                            const { sdkType, versions, latestVersion } = settlement.value
                            result[sdkType as SdkType] = {
                                versions,
                                latestVersion,
                            }
                        }
                    })

                    // Save to cache if we have data
                    if (Object.keys(result).length > 0) {
                        setGitHubCache(result)
                    }

                    return result
                },
            },
        ],
    })),

    reducers({
        // Track initialization events separately for demo purposes
        initializationEvents: [
            [] as EventType[],
            {
                loadRecentEventsSuccess: (_, { recentEvents }) => {
                    // For posthog-js SDK, filter events related to initialization
                    return recentEvents.filter(
                        (event) =>
                            event.properties?.$lib === 'web' &&
                            event.event === '$pageview' &&
                            event.properties?.hasOwnProperty('$posthog_initialized')
                    )
                },
            },
        ],

        // Persistent detection for multiple initializations
        multipleInitDetection: [
            { detected: false, detectedAt: '', affectedUrls: [], sessionCount: 0 } as MultipleInitDetection,
            {
                loadRecentEventsSuccess: (state, { recentEvents }) => {
                    // If we've already detected multiple inits, keep the persistent state
                    // Only update if we find NEW instances of the problem

                    const limitedEvents = recentEvents.slice(0, 15)

                    // Check for multiple initialization patterns
                    let newDetection = false
                    let exampleEventId: string | undefined
                    let exampleEventTimestamp: string | undefined
                    const newProblematicUrls = new Set<string>()
                    let sessionCount = 0

                    // Only look at events from the last 10 minutes to avoid cross-contamination between test scenarios
                    const tenMinutesAgo = Date.now() - 10 * 60 * 1000
                    const eventsByUser = limitedEvents
                        .filter(
                            (e) =>
                                e.properties?.$lib === 'web' &&
                                e.properties?.$session_id &&
                                e.properties?.$current_url &&
                                new Date(e.timestamp).getTime() > tenMinutesAgo // Only recent events
                        )
                        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

                    // console.log(`[SDK Doctor] Analyzing ${eventsByUser.length} web events from last 10 minutes`)

                    // Group events by distinct_id to track per-user patterns
                    const userEventGroups: Record<string, typeof eventsByUser> = {}
                    eventsByUser.forEach((event) => {
                        const distinctId = event.properties?.distinct_id || 'unknown'
                        if (!userEventGroups[distinctId]) {
                            userEventGroups[distinctId] = []
                        }
                        userEventGroups[distinctId].push(event)
                    })

                    // Track unique sessions
                    const uniqueSessions = new Set<string>()

                    // Check each user's events for multiple init patterns
                    Object.values(userEventGroups).forEach((userEvents) => {
                        for (let i = 1; i < userEvents.length; i++) {
                            const prevEvent = userEvents[i - 1]
                            const currEvent = userEvents[i]

                            const prevSessionId = prevEvent.properties?.$session_id
                            const currSessionId = currEvent.properties?.$session_id
                            const prevUrl = prevEvent.properties?.$current_url
                            const currUrl = currEvent.properties?.$current_url
                            const prevTime = new Date(prevEvent.timestamp).getTime()
                            const currTime = new Date(currEvent.timestamp).getTime()
                            const timeDiffSeconds = (currTime - prevTime) / 1000
                            const prevVersion = prevEvent.properties?.$lib_version
                            const currVersion = currEvent.properties?.$lib_version

                            // Track unique sessions
                            if (prevSessionId) {
                                uniqueSessions.add(prevSessionId)
                            }
                            if (currSessionId) {
                                uniqueSessions.add(currSessionId)
                            }

                            // Check each condition separately for better debugging
                            const hasSessionChange = prevSessionId !== currSessionId
                            const hasSameUrl = prevUrl === currUrl
                            const hasShortTimeGap = timeDiffSeconds < 30 && timeDiffSeconds > 0
                            const hasVersionGap = isSignificantVersionGap(prevVersion, currVersion)

                            // console.log(`[SDK Doctor] Event pair: ${prevVersion} → ${currVersion}`)
                            // console.log(`[SDK Doctor] Conditions: session=${hasSessionChange}, url=${hasSameUrl}, time=${hasShortTimeGap} (${timeDiffSeconds}s), version=${hasVersionGap}`)

                            // Detect: new session ID + same URL + tiny time gap + significant version difference
                            if (hasSessionChange && hasSameUrl && hasShortTimeGap && hasVersionGap) {
                                // console.log(`[SDK Doctor] ⚠️ DETECTION TRIGGERED: ${prevVersion} → ${currVersion} on ${currUrl}`)
                                // console.log(`[SDK Doctor] Sessions: ${prevSessionId?.substr(-8)} → ${currSessionId?.substr(-8)}, ${timeDiffSeconds}s gap`)
                                newDetection = true
                                newProblematicUrls.add(currUrl)

                                // Capture the first problematic event for linking
                                if (!exampleEventId && currEvent.id) {
                                    exampleEventId = currEvent.id
                                    exampleEventTimestamp = currEvent.timestamp
                                }

                                // console.log(`[SDK Doctor] Multiple init detected: ${prevSessionId} → ${currSessionId} on ${currUrl} (${timeDiffSeconds}s apart`)
                            }
                        }
                    })

                    sessionCount = uniqueSessions.size

                    // If we detect a new problem, update state
                    if (newDetection) {
                        return {
                            detected: true,
                            detectedAt: state.detectedAt || new Date().toISOString(), // Keep original detection time
                            exampleEventId: exampleEventId || state.exampleEventId, // Use new or keep existing
                            exampleEventTimestamp: exampleEventTimestamp || state.exampleEventTimestamp,
                            affectedUrls: Array.from(
                                new Set([...state.affectedUrls, ...Array.from(newProblematicUrls)])
                            ),
                            sessionCount: Math.max(sessionCount, state.sessionCount),
                        }
                    }

                    // If we had a previous detection but see sustained normal behavior, consider clearing it
                    if (state.detected && !newDetection) {
                        // Check if we have recent normal web events (single session across multiple events)
                        const recentWebEvents = limitedEvents
                            .filter((e) => e.properties?.$lib === 'web' && e.properties?.$session_id)
                            .slice(0, 10) // Look at the 10 most recent web events

                        if (recentWebEvents.length >= 5) {
                            // If the last 5+ web events all share the same session ID, consider the issue resolved
                            const sessionIds = new Set(recentWebEvents.map((e) => e.properties?.$session_id))

                            if (sessionIds.size === 1) {
                                // All recent events are from the same session - issue appears resolved
                                // console.log('[SDK Doctor] Multiple init issue appears resolved - clearing detection state')
                                return {
                                    detected: false,
                                    detectedAt: '',
                                    affectedUrls: [],
                                    sessionCount: 0,
                                }
                            }
                        }
                    }

                    // Keep existing state (either detected with no new evidence, or not detected)
                    return state
                },
            },
        ],

        // Feature flag misconfiguration detection
        featureFlagMisconfiguration: [
            {
                detected: false,
                detectedAt: '',
                flagsCalledBeforeLoading: [],
                sessionCount: 0,
            } as FeatureFlagMisconfiguration,
            {
                loadRecentEventsSuccess: (state, { recentEvents }) => {
                    // Only look at recent events to avoid cross-contamination
                    const tenMinutesAgo = Date.now() - 10 * 60 * 1000
                    const limitedEvents = recentEvents.slice(0, 15)

                    // Filter for feature flag events from the last 10 minutes
                    const flagEvents = limitedEvents
                        .filter(
                            (event) =>
                                event.event === '$feature_flag_called' &&
                                event.properties?.$lib === 'web' &&
                                new Date(event.timestamp).getTime() > tenMinutesAgo
                        )
                        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

                    // Find PostHog init events (pageviews with $lib initialization)
                    const initEvents = limitedEvents
                        .filter(
                            (event) =>
                                event.event === '$pageview' &&
                                event.properties?.$lib === 'web' &&
                                event.properties?.hasOwnProperty('$lib_version') &&
                                new Date(event.timestamp).getTime() > tenMinutesAgo
                        )
                        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

                    // Group events by session to track timing
                    const sessionEvents: Record<
                        string,
                        { flagEvents: typeof flagEvents; initEvents: typeof initEvents }
                    > = {}

                    flagEvents.forEach((event) => {
                        const sessionId = event.properties?.$session_id
                        if (sessionId) {
                            if (!sessionEvents[sessionId]) {
                                sessionEvents[sessionId] = { flagEvents: [], initEvents: [] }
                            }
                            sessionEvents[sessionId].flagEvents.push(event)
                        }
                    })

                    initEvents.forEach((event) => {
                        const sessionId = event.properties?.$session_id
                        if (sessionId) {
                            if (!sessionEvents[sessionId]) {
                                sessionEvents[sessionId] = { flagEvents: [], initEvents: [] }
                            }
                            sessionEvents[sessionId].initEvents.push(event)
                        }
                    })

                    // Detect flags called before PostHog init (no bootstrapping)
                    const problematicFlags = new Set<string>()
                    let exampleEventId: string | undefined
                    let exampleEventTimestamp: string | undefined
                    const uniqueSessions = new Set<string>()

                    Object.entries(sessionEvents).forEach(
                        ([sessionId, { flagEvents: sessionFlagEvents, initEvents: sessionInitEvents }]) => {
                            uniqueSessions.add(sessionId)

                            // If we have flag events but no init events in this session, or flag events before first init
                            if (sessionFlagEvents.length > 0) {
                                const firstInitTime =
                                    sessionInitEvents.length > 0
                                        ? new Date(sessionInitEvents[0].timestamp).getTime()
                                        : Infinity

                                sessionFlagEvents.forEach((flagEvent) => {
                                    const flagTime = new Date(flagEvent.timestamp).getTime()

                                    // Flag called before init or no init at all
                                    if (flagTime < firstInitTime) {
                                        const flagName = flagEvent.properties?.$feature_flag
                                        if (flagName) {
                                            problematicFlags.add(flagName)

                                            // Capture first example
                                            if (!exampleEventId && flagEvent.id) {
                                                exampleEventId = flagEvent.id
                                                exampleEventTimestamp = flagEvent.timestamp
                                            }
                                        }
                                    }
                                })
                            }
                        }
                    )

                    // If we detect new problems, update state
                    if (problematicFlags.size > 0) {
                        return {
                            detected: true,
                            detectedAt: state.detectedAt || new Date().toISOString(),
                            flagsCalledBeforeLoading: Array.from(
                                new Set([...state.flagsCalledBeforeLoading, ...Array.from(problematicFlags)])
                            ),
                            exampleEventId: exampleEventId || state.exampleEventId,
                            exampleEventTimestamp: exampleEventTimestamp || state.exampleEventTimestamp,
                            sessionCount: Math.max(uniqueSessions.size, state.sessionCount),
                        }
                    }

                    // Check if issue appears resolved (recent flag events with proper timing)
                    if (state.detected && problematicFlags.size === 0) {
                        const recentFlagEvents = flagEvents.slice(-5) // Last 5 flag events

                        if (recentFlagEvents.length >= 3) {
                            // If recent flag events all have proper timing relative to inits, consider resolved
                            const hasProperTiming = recentFlagEvents.every((flagEvent) => {
                                const sessionId = flagEvent.properties?.$session_id
                                const sessionInits = sessionEvents[sessionId]?.initEvents || []

                                if (sessionInits.length === 0) {
                                    return false
                                } // No init events

                                const flagTime = new Date(flagEvent.timestamp).getTime()
                                const initTime = new Date(sessionInits[0].timestamp).getTime()

                                return flagTime >= initTime // Flag called after init
                            })

                            if (hasProperTiming) {
                                return {
                                    detected: false,
                                    detectedAt: '',
                                    flagsCalledBeforeLoading: [],
                                    sessionCount: 0,
                                }
                            }
                        }
                    }

                    return state
                },
            },
        ],

        sdkVersionsMap: [
            {} as Record<string, SdkVersionInfo>,
            {
                loadRecentEvents: (state) => state, // Keep existing state while loading
                loadRecentEventsSuccess: (state, { recentEvents }) => {
                    // console.log('[SDK Doctor] Processing recent events:', recentEvents.length)
                    const sdkVersionsMap: Record<string, SdkVersionInfo> = {}

                    // Ensure we only look at the most recent 15 events maximum
                    const limitedEvents = recentEvents.slice(0, 15)

                    const webEvents = limitedEvents.filter((e) => e.properties?.$lib === 'web')

                    // Detect multiple SDK versions within the same session - a strong indicator of misconfiguration
                    // eslint-disable-next-line @typescript-eslint/no-unused-vars
                    const hasMultipleVersions = false
                    const problematicSessions = new Set<string>()
                    const problematicUrls = new Set<string>()

                    // Group events by session to find version conflicts
                    const sessionVersionMap: Record<string, Set<string>> = {} // session_id -> Set of versions

                    webEvents.forEach((event) => {
                        const sessionId = event.properties?.$session_id
                        const version = event.properties?.$lib_version

                        if (sessionId && version) {
                            if (!sessionVersionMap[sessionId]) {
                                sessionVersionMap[sessionId] = new Set()
                            }
                            sessionVersionMap[sessionId].add(version)
                        }
                    })

                    // Check for sessions with multiple versions
                    Object.entries(sessionVersionMap).forEach(([sessionId, versions]) => {
                        if (versions.size > 1) {
                            // hasMultipleVersions = true // Legacy - now handled by separate multipleInitDetection
                            problematicSessions.add(sessionId)
                        }
                    })

                    // Also check for rapid version changes within a short time window
                    const eventsByTime = webEvents
                        .filter((e) => e.properties?.$lib_version && e.properties?.$session_id)
                        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

                    for (let i = 1; i < eventsByTime.length; i++) {
                        const prevEvent = eventsByTime[i - 1]
                        const currEvent = eventsByTime[i]

                        const prevVersion = prevEvent.properties?.$lib_version
                        const currVersion = currEvent.properties?.$lib_version
                        const prevTime = new Date(prevEvent.timestamp).getTime()
                        const currTime = new Date(currEvent.timestamp).getTime()

                        // If different versions appear within 10 minutes in the same session
                        if (
                            prevVersion !== currVersion &&
                            prevEvent.properties?.$session_id === currEvent.properties?.$session_id &&
                            currTime - prevTime < 10 * 60 * 1000
                        ) {
                            // hasMultipleVersions = true // Legacy - now handled by separate multipleInitDetection
                            problematicSessions.add(currEvent.properties.$session_id)

                            // Track URLs where this happens
                            if (currEvent.properties.$current_url) {
                                problematicUrls.add(currEvent.properties.$current_url)
                            }
                        }
                    }

                    // Detect multiple initialization patterns - same URL, new session ID, tiny time gap
                    // eslint-disable-next-line @typescript-eslint/no-unused-vars
                    const hasMultipleInits = false
                    const initProblematicUrls = new Set<string>()

                    // Sort events by timestamp for temporal analysis
                    const eventsByUser = limitedEvents
                        .filter(
                            (e) =>
                                e.properties?.$lib === 'web' && e.properties?.$session_id && e.properties?.$current_url
                        )
                        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())

                    // Group events by distinct_id to track per-user patterns
                    const userEventGroups: Record<string, typeof eventsByUser> = {}
                    eventsByUser.forEach((event) => {
                        const distinctId = event.properties?.distinct_id || 'unknown'
                        if (!userEventGroups[distinctId]) {
                            userEventGroups[distinctId] = []
                        }
                        userEventGroups[distinctId].push(event)
                    })

                    // Check each user's events for multiple init patterns
                    Object.values(userEventGroups).forEach((userEvents) => {
                        for (let i = 1; i < userEvents.length; i++) {
                            const prevEvent = userEvents[i - 1]
                            const currEvent = userEvents[i]

                            const prevSessionId = prevEvent.properties?.$session_id
                            const currSessionId = currEvent.properties?.$session_id
                            const prevUrl = prevEvent.properties?.$current_url
                            const currUrl = currEvent.properties?.$current_url
                            const prevTime = new Date(prevEvent.timestamp).getTime()
                            const currTime = new Date(currEvent.timestamp).getTime()
                            const timeDiffSeconds = (currTime - prevTime) / 1000

                            const prevVersion = prevEvent.properties?.$lib_version
                            const currVersion = currEvent.properties?.$lib_version
                            const hasVersionGap = isSignificantVersionGap(prevVersion, currVersion)

                            // Detect: new session ID + same URL + tiny time gap + significant version difference
                            if (
                                prevSessionId !== currSessionId && // Different session IDs
                                prevUrl === currUrl && // Same URL
                                timeDiffSeconds < 30 && // Less than 30 seconds apart
                                timeDiffSeconds > 0 && // Ensure we have actual time progression
                                hasVersionGap // Only detect if versions suggest multiple inits (not auto-update)
                            ) {
                                // hasMultipleInits = true // Legacy - now handled by separate multipleInitDetection
                                initProblematicUrls.add(currUrl)

                                // console.log(`[SDK Doctor] Multiple init detected: ${prevSessionId} → ${currSessionId} on ${currUrl} (${timeDiffSeconds}s apart`)
                            }
                        }
                    })

                    // Merge multiple init URLs with version conflict URLs
                    initProblematicUrls.forEach((url) => problematicUrls.add(url))

                    // This reducer no longer handles multiple initialization detection
                    // That's now handled by the separate multipleInitDetection reducer

                    // Process all events to extract SDK versions
                    limitedEvents.forEach((event) => {
                        const lib = event.properties?.$lib
                        const libVersion = event.properties?.$lib_version

                        if (!lib || !libVersion) {
                            return
                        }

                        const key = `${lib}-${libVersion}`

                        if (!sdkVersionsMap[key]) {
                            // Determine SDK type from lib name
                            let type: SdkType = 'other'
                            if (lib === 'web') {
                                type = 'web'
                            } else if (lib === 'posthog-ios') {
                                type = 'ios'
                            } else if (lib === 'posthog-android') {
                                type = 'android'
                            } else if (lib === 'posthog-node') {
                                type = 'node'
                            } else if (lib === 'posthog-python') {
                                type = 'python'
                            } else if (lib === 'posthog-php') {
                                type = 'php'
                            } else if (lib === 'posthog-ruby') {
                                type = 'ruby'
                            } else if (lib === 'posthog-go') {
                                type = 'go'
                            } else if (lib === 'posthog-flutter') {
                                type = 'flutter'
                            } else if (lib === 'posthog-react-native') {
                                type = 'react-native'
                            }

                            // Copy existing data for this version if it exists
                            const existingData = state[key] || {}

                            // We'll update the isOutdated value after checking with latest versions
                            // For now, use the existing function as a fallback
                            const isOutdated =
                                existingData.isOutdated !== undefined
                                    ? existingData.isOutdated
                                    : checkIfVersionOutdated(lib, libVersion)

                            sdkVersionsMap[key] = {
                                ...existingData,
                                type,
                                version: libVersion,
                                isOutdated,
                                count: 1,
                                // Multiple init detection is now handled by the separate multipleInitDetection reducer
                                multipleInitializations: false, // Always false - use multipleInitDetection.detected instead
                                initCount: undefined,
                                initUrls: undefined,
                            }
                        } else {
                            sdkVersionsMap[key].count += 1
                        }
                    })

                    return sdkVersionsMap
                },
                loadLatestSdkVersionsSuccess: (state, { latestSdkVersions }) => {
                    // Re-evaluate all versions with the new data
                    const updatedMap = { ...state }

                    // Only process if we have data
                    if (Object.keys(latestSdkVersions).length > 0) {
                        Object.entries(updatedMap).forEach(([key, info]) => {
                            // Use the version directly from the info object instead of trying to parse from key
                            // This fixes the issue with libraries that have hyphens in their names
                            const version = info.version

                            // Map lib name to SDK type
                            const sdkType: SdkType = info.type

                            const { isOutdated, releasesAhead, latestVersion } = checkVersionAgainstLatest(
                                sdkType,
                                version,
                                latestSdkVersions
                            )

                            updatedMap[key] = {
                                ...info,
                                isOutdated,
                                releasesAhead,
                                latestVersion,
                            }
                        })
                    } else {
                        // If we couldn't get latest versions, fall back to the hardcoded check
                        Object.entries(updatedMap).forEach(([key, info]) => {
                            // Get the version directly from info object
                            const version = info.version

                            // Convert type to lib name for the hardcoded check
                            let libName = 'web'
                            if (info.type === 'ios') {
                                libName = 'posthog-ios'
                            }
                            if (info.type === 'android') {
                                libName = 'posthog-android'
                            }
                            if (info.type === 'node') {
                                libName = 'posthog-node'
                            }
                            if (info.type === 'python') {
                                libName = 'posthog-python'
                            }
                            if (info.type === 'php') {
                                libName = 'posthog-php'
                            }
                            if (info.type === 'ruby') {
                                libName = 'posthog-ruby'
                            }
                            if (info.type === 'go') {
                                libName = 'posthog-go'
                            }
                            if (info.type === 'flutter') {
                                libName = 'posthog-flutter'
                            }
                            if (info.type === 'react-native') {
                                libName = 'posthog-react-native'
                            }

                            // console.log(`[SDK Doctor] Fallback check for ${libName} version ${version}`)

                            updatedMap[key] = {
                                ...info,
                                isOutdated: checkIfVersionOutdated(libName, version),
                            }
                        })
                    }

                    return updatedMap
                },
            },
        ],
    }),

    selectors({
        sdkVersions: [
            (s) => [s.sdkVersionsMap],
            (sdkVersionsMap: Record<string, SdkVersionInfo>): SdkVersionInfo[] => {
                return Object.values(sdkVersionsMap).sort((a, b) => b.count - a.count)
            },
        ],

        outdatedSdkCount: [
            (s) => [s.sdkVersions],
            (sdkVersions: SdkVersionInfo[]): number => {
                return sdkVersions.filter((sdk) => sdk.isOutdated).length
            },
        ],

        multipleInitSdks: [
            (s) => [s.sdkVersions, s.multipleInitDetection],
            (sdkVersions: SdkVersionInfo[], multipleInitDetection: MultipleInitDetection): SdkVersionInfo[] => {
                // Use persistent detection state instead of just current event window
                if (multipleInitDetection.detected) {
                    // Return web SDK with the persistent detection info
                    return sdkVersions
                        .filter((sdk) => sdk.type === 'web')
                        .map((sdk) => ({
                            ...sdk,
                            multipleInitializations: true,
                            initCount: multipleInitDetection.sessionCount,
                            initUrls: multipleInitDetection.affectedUrls.map((url) => ({ url, count: 1 })),
                        }))
                }
                return sdkVersions.filter((sdk) => sdk.multipleInitializations)
            },
        ],

        sdkHealth: [
            (s) => [s.outdatedSdkCount, s.multipleInitSdks, s.featureFlagMisconfiguration],
            (
                outdatedSdkCount: number,
                multipleInitSdks: SdkVersionInfo[],
                featureFlagMisconfiguration: FeatureFlagMisconfiguration
            ): SdkHealthStatus => {
                // Feature flag misconfiguration is considered a critical issue
                if (featureFlagMisconfiguration.detected) {
                    return 'critical'
                }
                // Multiple initialization is considered a critical issue
                if (multipleInitSdks.length > 0) {
                    return 'critical'
                }
                // If there are any outdated SDKs, mark as warning
                // If there are 3 or more, mark as critical
                if (outdatedSdkCount >= 3) {
                    return 'critical'
                } else if (outdatedSdkCount > 0) {
                    return 'warning'
                }
                return 'healthy'
            },
        ],

        needsAttention: [
            (s) => [s.sdkHealth],
            (sdkHealth: SdkHealthStatus): boolean => {
                // For the button to be visible, we need a non-healthy status
                return sdkHealth !== 'healthy'
            },
        ],
    }),

    listeners(({ actions }) => ({
        loadRecentEventsSuccess: () => {
            // Once we have loaded events, fetch the latest versions to compare against
            actions.loadLatestSdkVersions()

            // Update GitHub releases cache for better version gap detection
            void updateReleasesCache()
        },
    })),

    afterMount(({ actions, cache }) => {
        // Load recent events when the logic is mounted
        actions.loadRecentEvents()

        // Start polling every 5 seconds
        cache.pollingInterval = window.setInterval(() => {
            actions.loadRecentEvents()
        }, 5000)
    }),

    beforeUnmount(({ cache }) => {
        // Clean up the interval when unmounting
        if (cache.pollingInterval) {
            window.clearInterval(cache.pollingInterval)
            cache.pollingInterval = null
        }
    }),
])

// Helper function to check if a version is outdated
function checkIfVersionOutdated(lib: string, version: string): boolean {
    // Add debug logs to trace execution
    // console.log(`[SDK Doctor] Checking if outdated: ${lib} version ${version}`)

    // This function now serves as a fallback when GitHub API data isn't available
    // It should match the logic in checkVersionAgainstLatest for consistency

    // Parse the version string into components
    const components = version.split('.')
    if (components.length < 2) {
        // console.log(`[SDK Doctor] Cannot determine version: ${version}`)
        return false // Can't determine
    }

    const major = parseInt(components[0])
    const minor = parseInt(components[1])

    // Debug log for PHP SDK specifically
    if (lib === 'posthog-php') {
        // console.log(
        //     `[SDK Doctor] PHP SDK check: version ${version}, major=${major}, minor=${minor}, isOutdated=${major < 3}`
        // )
    }

    // Hardcoded check for Node.js SDK
    if (lib === 'posthog-node') {
        // Consider outdated if below 4.17.0
        return major < 4 || (major === 4 && minor < 17)
    }

    // Align with the same version requirements used in checkVersionAgainstLatest
    if (lib === 'web') {
        // Consider web SDK outdated if below 1.85.0
        return major < 1 || (major === 1 && minor < 85)
    } else if (lib === 'posthog-ios') {
        return major < 1 || (major === 1 && minor < 4)
    } else if (lib === 'posthog-android') {
        return major < 1 || (major === 1 && minor < 4)
    } else if (lib === 'posthog-php') {
        return major < 3
    }

    // For all other SDKs, apply a generic rule that matches checkVersionAgainstLatest
    // This is approximate since we don't have the latest version data here
    return false
}

// Enhanced version comparison function using semver utilities
function checkVersionAgainstLatest(
    type: SdkType,
    version: string,
    latestVersionsData: Record<SdkType, { latestVersion: string; versions: string[] }>
): { isOutdated: boolean; releasesAhead?: number; latestVersion?: string } {
    // console.log(`[SDK Doctor] checkVersionAgainstLatest for ${type} version ${version}`)
    // console.log(`[SDK Doctor] Available data:`, Object.keys(latestVersionsData))

    // Convert type to lib name for consistency
    let lib = 'web'
    if (type === 'ios') {
        lib = 'posthog-ios'
    }
    if (type === 'android') {
        lib = 'posthog-android'
    }
    if (type === 'node') {
        lib = 'posthog-node'
    }
    if (type === 'python') {
        lib = 'posthog-python'
    }
    if (type === 'php') {
        lib = 'posthog-php'
    }
    if (type === 'ruby') {
        lib = 'posthog-ruby'
    }
    if (type === 'go') {
        lib = 'posthog-go'
    }
    if (type === 'flutter') {
        lib = 'posthog-flutter'
    }
    if (type === 'react-native') {
        lib = 'posthog-react-native'
    }

    // Hardcoded check for Node.js SDK
    if (type === 'node') {
        // Hardcoded latest version for Node.js SDK
        const mockLatestVersion = '4.17.1'

        try {
            // Parse version components
            const components = version.split('.')
            const major = parseInt(components[0])
            const minor = parseInt(components[1])

            // Check if version is outdated based on our consistent logic
            const isOutdated = major < 4 || (major === 4 && minor < 17)

            // Calculate releases ahead (mock value)
            let releasesAhead = 0

            if (major < 4) {
                releasesAhead = 10 // Major version behind is significant
            } else if (major === 4 && minor < 17) {
                releasesAhead = 17 - minor // Minor versions behind
            }

            return {
                isOutdated,
                releasesAhead,
                latestVersion: mockLatestVersion,
            }
        } catch (e) {
            // If parsing fails, use the fallback check
            return {
                isOutdated: checkIfVersionOutdated(lib, version),
                latestVersion: mockLatestVersion,
            }
        }
    }

    // If we don't have data for this SDK type or the SDK type is "other", fall back to hardcoded check
    if (!latestVersionsData[type] || type === 'other') {
        // console.log(`[SDK Doctor] Falling back to hardcoded check for ${type} (lib=${lib})`)
        const isOutdated = checkIfVersionOutdated(lib, version)
        // console.log(`[SDK Doctor] Hardcoded check result for ${lib} ${version}: isOutdated=${isOutdated}`)
        return { isOutdated }
    }

    const latestVersion = latestVersionsData[type].latestVersion
    const allVersions = latestVersionsData[type].versions

    try {
        // Parse versions for comparison
        const currentVersionParsed = parseVersion(version)
        const latestVersionParsed = parseVersion(latestVersion)

        // Check if versions differ
        const diff = diffVersions(latestVersionParsed, currentVersionParsed)

        // Count number of versions behind
        const versionIndex = allVersions.indexOf(version)
        let releasesBehind = versionIndex === -1 ? -1 : versionIndex

        // Or estimate based on semantic version difference if we don't have the exact version
        if (releasesBehind === -1 && diff) {
            if (diff.kind === 'major') {
                releasesBehind = diff.diff * 10 // Major version differences are significant
            } else if (diff.kind === 'minor') {
                releasesBehind = diff.diff // Minor versions represent normal releases
            } else {
                releasesBehind = Math.floor(diff.diff / 3) // Patch versions might be less significant
            }
        }

        // Consider outdated if 2+ versions behind
        return {
            isOutdated: releasesBehind >= 2,
            releasesAhead: Math.max(0, releasesBehind),
            latestVersion,
        }
    } catch (e) {
        // If we can't parse the versions, fall back to the hardcoded check
        // console.log(`[SDK Doctor] Error parsing versions, falling back to hardcoded check for ${lib}: ${e}`)

        return {
            isOutdated: checkIfVersionOutdated(lib, version),
            latestVersion,
        }
    }
}
