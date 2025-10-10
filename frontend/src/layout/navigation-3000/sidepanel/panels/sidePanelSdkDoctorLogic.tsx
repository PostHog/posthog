/* oxlint-disable no-console */
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
// import { isNotNil } from 'lib/utils' // Unused after bulk fetching removal
import { getAppContext } from 'lib/utils/getAppContext'
import { diffVersions, parseVersion } from 'lib/utils/semver'
// Removed tryParseVersion (unused after bulk fetching removal)
import { teamLogic } from 'scenes/teamLogic'

import { EventType, EventsListQueryParams } from '~/types'

import {
    type FeatureFlagMisconfiguration,
    detectFeatureFlagMisconfiguration,
    isDemoMode,
} from './sdk_doctor/featureFlagDetection'
import { processAllSdkDetections } from './sdk_doctor/sdkDetectionProcessing'
import type { SdkHealthStatus, SdkType, SdkVersionInfo } from './sdk_doctor/types'
import {
    DEVICE_CONTEXT_CONFIG,
    calculateVersionAge,
    categorizeEventVolume,
    determineDeviceContext,
} from './sdk_doctor/utils'
import { updateSdkVersionInfo } from './sdk_doctor/versionChecking'
import type { sidePanelSdkDoctorLogicType } from './sidePanelSdkDoctorLogicType'

// Re-export types for external consumption (required by Kea type generator)
export type { SdkType, SdkVersionInfo, SdkHealthStatus } from './sdk_doctor/types'

/**
 * SDK Doctor - PostHog SDK Health Monitoring
 *
 * Detects installed SDKs and their versions across a team's events.
 * Provides smart version outdatedness detection and feature flag timing analysis.
 *
 * Architecture:
 * - Backend detection: Team SDK detections cached server-side (24h Redis)
 * - Version checking: Per-SDK GitHub API queries cached server-side (24h Redis)
 * - Smart semver: Contextual thresholds (7-day grace, 3+ minors, 5+ patches)
 * - Feature flags: Contextual timing detection (0ms/350ms/500ms thresholds)
 *
 * Module structure:
 * - types.ts: Shared type definitions
 * - utils.ts: Device context and event volume utilities
 * - sdkDetectionProcessing.ts: Backend detection processing
 * - versionChecking.ts: Async version checking helpers
 * - featureFlagDetection.ts: Feature flag timing analysis
 */

// Debug mode detection following PostHog's standard pattern
const IS_DEBUG_MODE = (() => {
    const appContext = getAppContext()
    return appContext?.preflight?.is_debug || process.env.NODE_ENV === 'test'
})()

// Client-side caching removed - now handled server-side with Redis

// DISABLED: Bulk GitHub API functions (causing 403 errors) - kept for future per-SDK implementation
/*

// Fetch Python SDK release dates from GitHub Releases API for time-based detection

// Fetch React Native SDK release dates from GitHub Releases API for time-based detection

// Fetch Flutter SDK release dates from GitHub Releases API for time-based detection

*/

// Fetch Node.js SDK release dates - REMOVED: Now handled by server API with proper caching and rate limiting

// Track which SDK types we've already logged to reduce verbosity
const loggedSdkTypes = new Set<SdkType>()
const loggedVersionChecks = new Set<string>()

/**
 * Fetches SDK version data from the backend API.
 *
 * This function queries the server-side cached GitHub API data for a specific SDK.
 * The backend maintains a 24-hour Redis cache to avoid rate limiting and improve performance.
 *
 * @param sdkType - The SDK type to fetch data for (e.g., 'web', 'python', 'node')
 * @returns Object containing:
 *   - latestVersion: The most recent version string
 *   - versions: Array of all version strings in descending order
 *   - releaseDates: Optional map of version -> ISO date for time-based detection
 * @returns null if the backend request fails or the SDK is not supported
 */
const fetchSdkData = async (
    sdkType: SdkType
): Promise<{ latestVersion: string; versions: string[]; releaseDates?: Record<string, string> } | null> => {
    const shouldLog = IS_DEBUG_MODE && !loggedSdkTypes.has(sdkType)
    if (shouldLog) {
        console.info(
            `[SDK Doctor] Checking if ${sdkType.charAt(0).toUpperCase() + sdkType.slice(1)} SDK info is cached on server...`
        )
    }
    try {
        const response = await api.get(`api/github-sdk-versions/${sdkType}`)
        if (response.latestVersion && response.versions) {
            if (shouldLog) {
                if (response.cached) {
                    console.info(
                        `[SDK Doctor] ${sdkType.charAt(0).toUpperCase() + sdkType.slice(1)} SDK details successfully read from server CACHE`
                    )
                } else {
                    console.info(
                        `[SDK Doctor] ${sdkType.charAt(0).toUpperCase() + sdkType.slice(1)} SDK info not found in CACHE, querying GitHub API`
                    )
                    console.info(
                        `[SDK Doctor] ${sdkType.charAt(0).toUpperCase() + sdkType.slice(1)} SDK info received from GitHub. CACHED successfully on the server`
                    )
                }
                loggedSdkTypes.add(sdkType)
            }
            return {
                latestVersion: response.latestVersion,
                versions: response.versions,
                releaseDates: response.releaseDates || {},
            }
        }
    } catch (error) {
        console.warn(`[SDK Doctor] Failed to fetch ${sdkType} data from backend:`, error)
        posthog.captureException(error)
    }

    // If backend fails, return null (no frontend fallback)
    return null
}

export const sidePanelSdkDoctorLogic = kea<sidePanelSdkDoctorLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSdkDoctorLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadRecentEvents: true,
        loadLatestSdkVersions: true,
        loadTeamSdkDetections: (forceRefresh?: boolean) => ({ forceRefresh }),
        updateSdkVersionsMap: (updatedMap: Record<string, SdkVersionInfo>) => ({ updatedMap }),
    }),

    loaders(({ values }) => ({
        recentEvents: [
            [] as EventType[],
            {
                loadRecentEvents: async () => {
                    const teamId = values.currentTeamId || undefined
                    try {
                        // Simple fetch: recent events from last 24 hours, up to 50 events
                        const params: EventsListQueryParams = {
                            limit: 50,
                            orderBy: ['-timestamp'],
                            after: '-24h',
                        }

                        const response = await api.events.list(params, 50, teamId)

                        if (IS_DEBUG_MODE) {
                            console.info(`[SDK Doctor] Loaded ${response.results.length} events from last 24h`)
                        }

                        return response.results
                    } catch (error) {
                        console.error('Error loading events:', error)
                        posthog.captureException(error)
                        return values.recentEvents || [] // Return existing data on error
                    }
                },
            },
        ],

        // Fetch latest SDK versions from GitHub API
        latestSdkVersions: [
            {} as Record<
                SdkType,
                {
                    latestVersion: string
                    versions: string[]
                    releaseDates?: Record<string, string> // version -> ISO date
                }
            >,
            {
                loadLatestSdkVersions: async () => {
                    // No bulk fetching needed - individual SDKs are processed via per-SDK server endpoints
                    // This loader exists only to trigger the success handler for async time-based detection
                    return {} as Record<
                        SdkType,
                        { latestVersion: string; versions: string[]; releaseDates?: Record<string, string> }
                    >
                },
            },
        ],

        // Fetch team SDK detections from backend (server-side cached)
        teamSdkDetections: [
            null as {
                teamId: number
                detections: Array<{
                    type: SdkType
                    version: string
                    count: number
                    lastSeen: string
                }>
                cached: boolean
                queriedAt: string
            } | null,
            {
                loadTeamSdkDetections: async ({ forceRefresh }) => {
                    if (IS_DEBUG_MODE) {
                        console.info('[SDK Doctor] Loading team SDK detections from backend', { forceRefresh })
                    }
                    try {
                        const url = forceRefresh ? 'api/detected-sdks/?force_refresh=true' : 'api/detected-sdks/'
                        const response = await api.get(url)
                        if (IS_DEBUG_MODE) {
                            console.info('[SDK Doctor] Team SDK detections response:', response)
                            console.info(
                                `[SDK Doctor] Loaded ${response.detections?.length || 0} SDK detections from backend (cached: ${response.cached}, forceRefresh: ${forceRefresh})`
                            )
                        }
                        return response
                    } catch (error) {
                        console.error('[SDK Doctor] Error loading team SDK detections:', error)
                        posthog.captureException(error)
                        return null
                    }
                },
            },
        ],
    })),

    reducers({
        // Feature flag misconfiguration detection with contextual threshold system
        featureFlagMisconfiguration: [
            {
                detected: false,
                detectedAt: '',
                flagsCalledBeforeLoading: [],
                flagExampleEvents: {},
                sessionCount: 0,
            } as FeatureFlagMisconfiguration,
            {
                loadRecentEventsSuccess: (state, { recentEvents }) => {
                    return detectFeatureFlagMisconfiguration(state, recentEvents, IS_DEBUG_MODE)
                },
            },
        ],

        sdkVersionsMap: [
            {} as Record<string, SdkVersionInfo>,
            {
                loadRecentEvents: (state) => state, // Keep existing state while loading
                loadTeamSdkDetectionsSuccess: (state, { teamSdkDetections }) => {
                    if (!teamSdkDetections?.detections) {
                        return state
                    }

                    if (IS_DEBUG_MODE) {
                        console.info(
                            `[SDK Doctor] Processing ${teamSdkDetections.detections.length} team SDK detections from backend`
                        )
                    }

                    // Process all SDK detections using shared helper
                    const newMap = {
                        ...state,
                        ...processAllSdkDetections(teamSdkDetections.detections, IS_DEBUG_MODE),
                    }

                    if (IS_DEBUG_MODE) {
                        const sdkCount = Object.keys(newMap).length
                        console.info(`[SDK Doctor] Processed detections into ${sdkCount} SDK version entries`)
                    }

                    return newMap
                },
                loadRecentEventsSuccess: (state, { recentEvents }) => {
                    // Start with existing state to preserve Web, Python, Node.js, React Native, Flutter, iOS, Android, Go, PHP, Ruby, Elixir, and .NET SDK data from teamSdkDetections
                    // We'll only process non-Web/Python/Node/React Native/Flutter/iOS/Android/Go/PHP/Ruby/Elixir/.NET SDKs from events (these come from backend)
                    const sdkVersionsMap: Record<string, SdkVersionInfo> = { ...state }

                    // Use all events from our strategy-based fetch (up to strategy.maxEvents)
                    const limitedEvents = recentEvents.slice(0, 30) // Allow up to 30 events

                    // Filter out PostHog's internal UI events (URLs containing /project/1/) when in development
                    // Also filter out posthog-js-lite events as requested
                    // In dev mode, also filter out test@posthog.com events (dev UI interactions)
                    const customerEvents = limitedEvents.filter((event) => {
                        // Always filter these
                        if (event.properties?.$current_url?.includes('/project/1')) {
                            return false
                        }
                        if (event.properties?.$lib === 'posthog-js-lite') {
                            return false
                        }

                        // Additional filtering in dev mode
                        if (isDemoMode()) {
                            // Filter test@posthog.com events
                            if (
                                event.properties?.email === 'test@posthog.com' ||
                                event.distinct_id === 'test@posthog.com'
                            ) {
                                return false
                            }

                            // Filter PostHog's internal Python SDK events more aggressively
                            if (event.properties?.$lib === 'posthog-python') {
                                // Check if this looks like an internal PostHog backend event
                                // Internal events often lack user-specific properties but have system properties
                                const hasTestDistinctId = event.distinct_id?.startsWith('test-')
                                const hasUserEmail =
                                    event.properties?.email && event.properties.email !== 'test@posthog.com'
                                const hasCustomUrl =
                                    event.properties?.$current_url &&
                                    !event.properties.$current_url.includes('localhost')

                                // If it's a test event (distinct_id starts with 'test-'), allow it
                                if (hasTestDistinctId) {
                                    console.info('[SDK Doctor] Allowing test Python event:', event.distinct_id)
                                    return true
                                }

                                // If it has real user properties, allow it
                                if (hasUserEmail || hasCustomUrl) {
                                    return true
                                }

                                // Otherwise, it's likely an internal PostHog backend event - filter it
                                return false
                            }

                            // Filter localhost web SDK events from PostHog's own frontend
                            if (event.properties?.$lib === 'web') {
                                const hasLocalhostHost = event.properties?.$host?.includes('localhost')
                                const hasLocalhostUrl = event.properties?.$current_url?.includes('localhost:8010')
                                if (hasLocalhostHost || hasLocalhostUrl) {
                                    return false
                                }
                            }
                        }

                        return true
                    })

                    if (isDemoMode()) {
                        const filtered = limitedEvents.length - customerEvents.length
                        if (filtered > 0) {
                            console.info(
                                `[SDK Doctor] Dev mode: Filtered out ${filtered} internal events (${limitedEvents.length} -> ${customerEvents.length})`
                            )
                        }

                        // CRITICAL FIX: If all events were filtered out in dev mode, preserve Web, Python, Node.js, React Native, Flutter, iOS, Android, Go, PHP, Ruby, Elixir, and .NET SDKs from backend
                        if (customerEvents.length === 0 && limitedEvents.length > 0) {
                            console.info(
                                '[SDK Doctor] Dev mode: All events filtered - preserving Web, Python, Node.js, React Native, Flutter, iOS, Android, Go, PHP, Ruby, Elixir, and .NET SDKs from backend'
                            )
                            // Keep existing state which contains Web, Python, Node.js, React Native, Flutter, iOS, Android, Go, PHP, Ruby, Elixir, and .NET SDK data from teamSdkDetections
                            return state
                        }
                    }

                    // Process all events to extract SDK versions
                    customerEvents.forEach((event) => {
                        const lib = event.properties?.$lib
                        const libVersion = event.properties?.$lib_version

                        if (!lib || !libVersion) {
                            return
                        }

                        // Skip Web, Python, Node.js, React Native, Flutter, iOS, Android, Go, PHP, Ruby, Elixir, and .NET SDKs - they're handled by teamSdkDetections from backend
                        if (
                            lib === 'web' ||
                            lib === 'posthog-python' ||
                            lib === 'posthog-node' ||
                            lib === 'posthog-react-native' ||
                            lib === 'posthog-flutter' ||
                            lib === 'posthog-ios' ||
                            lib === 'posthog-android' ||
                            lib === 'posthog-go' ||
                            lib === 'posthog-php' ||
                            lib === 'posthog-ruby' ||
                            lib === 'posthog-elixir' ||
                            lib === 'posthog-dotnet'
                        ) {
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
                            } else if (lib === 'posthog-dotnet') {
                                type = 'dotnet'
                            } else if (lib === 'posthog-elixir') {
                                type = 'elixir'
                            }

                            // Copy existing data for this version if it exists
                            const existingData = state[key] || {}

                            // We'll update the isOutdated value after checking with latest versions
                            // If no existing data, mark as not outdated initially (will be updated by version check)
                            const isOutdated = existingData.isOutdated !== undefined ? existingData.isOutdated : false

                            sdkVersionsMap[key] = {
                                ...existingData,
                                type,
                                version: libVersion,
                                isOutdated,
                                count: 1,
                            }
                        } else {
                            sdkVersionsMap[key].count += 1
                        }
                    })

                    // Clean up stale detections: Remove SDKs from state that weren't seen in current events
                    // This prevents Python SDK from persisting between scans when it's been filtered out
                    if (isDemoMode()) {
                        const currentSDKTypes = new Set(Object.values(sdkVersionsMap).map((info) => info.type))
                        for (const [key] of Object.entries(state)) {
                            if (!sdkVersionsMap[key] && currentSDKTypes.size > 0) {
                                // This SDK was in previous state but not in current events
                            }
                        }
                    }

                    return sdkVersionsMap
                },
                loadLatestSdkVersionsSuccess: (state, { latestSdkVersions }) => {
                    // Re-evaluate all versions with the new data
                    const updatedMap = { ...state }

                    // Skip all time-based detection SDKs - they'll be handled asynchronously in the listener
                    for (const [key, info] of Object.entries(updatedMap)) {
                        const version = info.version
                        const sdkType: SdkType = info.type

                        // Skip time-based detection SDKs - they'll be handled asynchronously in the listener
                        if (
                            [
                                'web',
                                'python',
                                'node',
                                'react-native',
                                'flutter',
                                'ios',
                                'android',
                                'go',
                                'ruby',
                                'php',
                                'elixir',
                                'dotnet',
                            ].includes(sdkType)
                        ) {
                            continue
                        }

                        let versionCheckResult
                        try {
                            // Use old method for non-Go SDKs (requires latestSdkVersions data)
                            if (Object.keys(latestSdkVersions).length > 0) {
                                versionCheckResult = checkVersionAgainstLatest(sdkType, version, latestSdkVersions)
                            } else {
                                // No data available for non-Go SDKs
                                versionCheckResult = {
                                    isOutdated: false,
                                    releasesAhead: 0,
                                    latestVersion: undefined,
                                    releaseDate: undefined,
                                    daysSinceRelease: undefined,
                                    isAgeOutdated: false,
                                    deviceContext: determineDeviceContext(sdkType),
                                }
                            }
                        } catch (error) {
                            console.warn(`[SDK Doctor] Error checking version for ${sdkType} ${version}:`, error)
                            posthog.captureException(error)
                            // Fallback to basic info
                            versionCheckResult = {
                                isOutdated: false,
                                releasesAhead: 0,
                                latestVersion: undefined,
                                releaseDate: undefined,
                                daysSinceRelease: undefined,
                                isAgeOutdated: false,
                                deviceContext: determineDeviceContext(sdkType),
                            }
                        }

                        const {
                            isOutdated,
                            releasesAhead,
                            latestVersion,
                            // NEW properties
                            releaseDate,
                            daysSinceRelease,
                            isAgeOutdated,
                            error,
                        } = versionCheckResult

                        // Get deviceContext, with fallback if not provided
                        const deviceContext =
                            'deviceContext' in versionCheckResult
                                ? versionCheckResult.deviceContext
                                : determineDeviceContext(sdkType)

                        updatedMap[key] = {
                            ...info,
                            isOutdated,
                            releasesAhead,
                            latestVersion,
                            // NEW properties
                            releaseDate,
                            daysSinceRelease,
                            isAgeOutdated,
                            deviceContext,
                            eventVolume: categorizeEventVolume(info.count),
                            lastSeenTimestamp: new Date().toISOString(), // Current processing time
                            error,
                        }
                    }

                    // If no SDKs were detected after filtering, return empty map in dev mode
                    // This prevents stale detections from persisting
                    if (isDemoMode() && Object.keys(updatedMap).length === 0) {
                        return {} // Clear all detections
                    }

                    // For Go SDK, we'll handle async processing in a listener
                    // For now, just return the state and let the listener handle Go SDK updates
                    return updatedMap
                },
                updateSdkVersionsMap: (_, { updatedMap }) => {
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

        sdkHealth: [
            (s) => [s.outdatedSdkCount, s.featureFlagMisconfiguration],
            (outdatedSdkCount: number, featureFlagMisconfiguration: FeatureFlagMisconfiguration): SdkHealthStatus => {
                // Feature flag misconfiguration is considered a critical issue
                if (featureFlagMisconfiguration.detected) {
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

        // Separate status for menu icon that includes "Close enough" SDKs
        menuIconStatus: [
            (s) => [s.sdkHealth, s.sdkVersions],
            (sdkHealth: SdkHealthStatus, sdkVersions: SdkVersionInfo[]): SdkHealthStatus => {
                // If we already have critical or warning status from sdkHealth, use that
                if (sdkHealth !== 'healthy') {
                    return sdkHealth
                }

                // Check for "Close enough" SDKs (not outdated, but not current either)
                const hasCloseEnoughSdks = sdkVersions.some(
                    (sdk) => !sdk.isOutdated && sdk.latestVersion && sdk.version !== sdk.latestVersion
                )

                if (hasCloseEnoughSdks) {
                    return 'warning' // This will show yellow circle with checkmark
                }

                return 'healthy' // Green circle with checkmark
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadTeamSdkDetectionsSuccess: async () => {
            if (IS_DEBUG_MODE) {
                console.info('[SDK Doctor] Team SDK detections loaded, triggering version checks')
            }
            // Trigger async version checking for Web SDK
            actions.loadLatestSdkVersions()
        },
        loadRecentEventsSuccess: async () => {
            // Fetch the latest versions to compare against for outdated version detection
            actions.loadLatestSdkVersions()
        },
        loadLatestSdkVersionsSuccess: async () => {
            // Skip async processing if SDK map is empty (all events were filtered in dev mode)
            if (Object.keys(values.sdkVersionsMap).length === 0) {
                if (isDemoMode()) {
                    console.info('[SDK Doctor] Dev mode: SDK map is empty after filtering, skipping async processing')
                }
                return
            }

            // Handle async processing for all time-based detection SDKs
            const updatedMap = { ...values.sdkVersionsMap }
            const timeBasedSdks: SdkType[] = [
                'web',
                'python',
                'node',
                'react-native',
                'flutter',
                'ios',
                'android',
                'go',
                'ruby',
                'php',
                'elixir',
                'dotnet',
            ]

            // Check if we have any time-based detection SDKs to process
            const hasTimeBasedSdks = Object.values(updatedMap).some((info) => timeBasedSdks.includes(info.type))

            if (hasTimeBasedSdks) {
                // Process time-based detection SDKs asynchronously
                for (const [key, info] of Object.entries(updatedMap)) {
                    if (timeBasedSdks.includes(info.type)) {
                        // Use shared helper to update SDK version info
                        // Generate human-readable SDK name for logging (e.g., "Go", "Web", "React Native")
                        const sdkName = info.type
                            .split('-')
                            .map((word: string) => word.charAt(0).toUpperCase() + word.slice(1))
                            .join(' ')

                        updatedMap[key] = await updateSdkVersionInfo(
                            info,
                            checkVersionAgainstLatestAsync,
                            determineDeviceContext,
                            categorizeEventVolume,
                            sdkName
                        )
                    }
                }

                // Update the state with the processed SDK data
                actions.updateSdkVersionsMap(updatedMap)
            }
        },
    })),

    afterMount(({ actions }) => {
        // Load team SDK detections from backend (cached server-side)
        actions.loadTeamSdkDetections()
        // Load recent events once when the panel is opened
        actions.loadRecentEvents()
    }),
])

/**
 * Async version checking with on-demand SDK data fetching.
 *
 * This function fetches SDK version data from the backend and delegates to
 * the synchronous checkVersionAgainstLatest for the actual comparison logic.
 * It's used for time-based detection SDKs that require GitHub release dates.
 *
 * @param type - SDK type to check
 * @param version - Current version string to evaluate
 * @returns Promise resolving to version status object with:
 *   - isOutdated: Whether the version should be flagged
 *   - releasesAhead: Number of releases between current and latest
 *   - latestVersion: The most recent version available
 *   - releaseDate: ISO date when current version was released
 *   - daysSinceRelease: Age of current version in days
 *   - isAgeOutdated: Whether version is outdated by age alone (for "Old" badge)
 *   - error: Error message if fetch fails
 */
async function checkVersionAgainstLatestAsync(
    type: SdkType,
    version: string
): Promise<{
    isOutdated: boolean
    releasesAhead?: number
    latestVersion?: string
    releaseDate?: string
    daysSinceRelease?: number
    isAgeOutdated?: boolean
    error?: string
}> {
    try {
        // Fetch SDK data on-demand (with caching)
        const sdkData = await fetchSdkData(type)
        if (!sdkData) {
            // SDK not implemented for per-SDK fetching yet, return neutral result
            return {
                isOutdated: false,
                releasesAhead: 0,
                latestVersion: undefined,
                releaseDate: undefined,
                daysSinceRelease: undefined,
                isAgeOutdated: false,
            }
        }

        // Use the existing logic with the fetched data - use spread to preserve all properties
        const latestVersionsData = { [type]: { ...sdkData } } as Record<
            SdkType,
            { latestVersion: string; versions: string[]; releaseDates?: Record<string, string> }
        >

        // Debug: Verify releaseDates are preserved
        if (type === 'go' && IS_DEBUG_MODE) {
        }

        return checkVersionAgainstLatest(type, version, latestVersionsData)
    } catch (error) {
        console.warn(`[SDK Doctor] Error in async version check for ${type}:`, error)
        posthog.captureException(error)
        return {
            isOutdated: false,
            releasesAhead: 0,
            error: 'Failed to fetch version data',
        }
    }
}

/**
 * Smart semver detection with age-based thresholds.
 *
 * This is the core version comparison logic that determines if an SDK version is outdated.
 * It applies contextual rules based on semantic versioning and release age to avoid false positives.
 *
 * Detection thresholds:
 * - **Grace period**: Versions <7 days old are NEVER flagged (even if major version behind)
 * - **Major**: Always flag if major version behind (1.x → 2.x) OR >1 year old
 * - **Minor**: Flag if 3+ minors behind OR >6 months old
 * - **Patch**: Flag if 5+ patches behind OR >3 months old
 *
 * The grace period prevents nagging teams about brand-new releases they haven't had time to upgrade to.
 * The age-based thresholds catch abandoned projects using very old versions.
 *
 * @param type - SDK type to check (e.g., 'web', 'python', 'node')
 * @param version - Current version string to evaluate
 * @param latestVersionsData - Version data from GitHub API including:
 *   - latestVersion: Most recent version string
 *   - versions: All versions in descending order
 *   - releaseDates: Map of version -> ISO date for time-based checks
 * @returns Object containing:
 *   - isOutdated: Whether version should be flagged (uses smart semver logic)
 *   - releasesAhead: Number of releases between current and latest
 *   - latestVersion: The most recent version available
 *   - releaseDate: ISO date when current version was released
 *   - daysSinceRelease: Age of current version in days
 *   - isAgeOutdated: Whether version is outdated by age alone (for "Old" badge)
 *   - deviceContext: Device platform category (mobile/desktop/mixed)
 *   - error: Error message if version parsing fails
 */
function checkVersionAgainstLatest(
    type: SdkType,
    version: string,
    latestVersionsData: Record<
        SdkType,
        {
            latestVersion: string
            versions: string[]
            releaseDates?: Record<string, string>
        }
    >
): {
    isOutdated: boolean
    releasesAhead?: number
    latestVersion?: string
    // NEW returns
    releaseDate?: string
    daysSinceRelease?: number
    isAgeOutdated?: boolean
    deviceContext?: 'mobile' | 'desktop' | 'mixed'
    error?: string
} {
    // TODO: Node.js now uses CHANGELOG.md data - removed hardcoded version logic

    // If we don't have data for this SDK type or the SDK type is "other", return error state
    if (!latestVersionsData[type] || type === 'other') {
        const errorMessage = `The Doctor is unavailable. Please try again later.`
        return {
            isOutdated: false,
            error: errorMessage,
            latestVersion: undefined,
            releaseDate: undefined,
            daysSinceRelease: undefined,
            isAgeOutdated: false,
            deviceContext: determineDeviceContext(type),
        }
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

        // Basic release count logic first (will be enhanced with time-based logic below)

        if (IS_DEBUG_MODE) {
        }

        // Age-based analysis
        const deviceContext = determineDeviceContext(type)
        const releaseDates = latestVersionsData[type]?.releaseDates
        const releaseDate = releaseDates?.[version]

        // Debug logging for Go SDK
        if (type === 'go') {
        }

        let daysSinceRelease: number | undefined
        let isAgeOutdated = false

        if (releaseDate) {
            daysSinceRelease = calculateVersionAge(releaseDate)
            const weeksOld = daysSinceRelease / 7

            // Age-based outdated detection: >8 weeks old AND newer releases exist
            isAgeOutdated = weeksOld > DEVICE_CONTEXT_CONFIG.ageThresholds.warnAfterWeeks && releasesBehind > 0
        }

        // Grace period: Don't flag versions released <7 days ago (even if major version behind)
        // This gives teams time to upgrade before we nag them about new releases
        let isRecentRelease = false
        const GRACE_PERIOD_DAYS = 7

        if (daysSinceRelease !== undefined) {
            isRecentRelease = daysSinceRelease < GRACE_PERIOD_DAYS
        }
        // Note: If daysSinceRelease is undefined (e.g., failed releases not in GitHub),
        // we continue with release count logic only - this is intentional

        // Smart version detection based on semver difference
        let isOutdated = false

        // Apply grace period first - don't flag anything <7 days old
        if (isRecentRelease) {
            isOutdated = false
        } else if (diff && diff.kind === 'major') {
            // Major version behind (1.x → 2.x): Always flag as outdated (also checked: >1 year below)
            isOutdated = true
        } else if (diff && diff.kind === 'minor') {
            // Minor version behind (1.2.x → 1.5.x): Flag if 3+ minors behind OR >6 months old
            const sixMonthsInDays = 180
            const isMinorOutdatedByCount = diff.diff >= 3
            const isMinorOutdatedByAge = daysSinceRelease !== undefined && daysSinceRelease > sixMonthsInDays
            isOutdated = isMinorOutdatedByCount || isMinorOutdatedByAge
        } else if (diff && diff.kind === 'patch') {
            // Patch version behind (1.2.3 → 1.2.6): Flag if 5+ patches behind OR >3 months old
            const threeMonthsInDays = 90
            const isPatchOutdatedByCount = diff.diff >= 5
            const isPatchOutdatedByAge = daysSinceRelease !== undefined && daysSinceRelease > threeMonthsInDays
            isOutdated = isPatchOutdatedByCount || isPatchOutdatedByAge
        } else if (!diff || diff.diff === 0) {
            // Current version matches latest
            isOutdated = false
        }
        // Note: Removed fallback release count logic - smart semver detection handles all cases now

        // Additional check: Flag if version is more than 1 year old (regardless of semver difference)
        const oneYearInDays = 365
        if (!isOutdated && daysSinceRelease !== undefined && daysSinceRelease > oneYearInDays) {
            isOutdated = true
        }

        // Log only once per SDK type to reduce verbosity
        const logKey = `${type}`
        const shouldLogVersionCheck = IS_DEBUG_MODE && !loggedVersionChecks.has(logKey)
        if (shouldLogVersionCheck) {
            console.info(
                `[SDK Doctor] Smart detection: diff=${diff ? `${diff.kind} ${diff.diff}` : 'none'}, daysSinceRelease=${daysSinceRelease}, isRecentRelease=${isRecentRelease}`
            )
            console.info(
                `[SDK Doctor] Final result: isOutdated=${isOutdated} (releasesBehind=${releasesBehind}, isAgeOutdated=${isAgeOutdated})`
            )
            loggedVersionChecks.add(logKey)
        }

        return {
            isOutdated, // Use smart semver result only - don't combine with isAgeOutdated
            releasesAhead: Math.max(0, releasesBehind),
            latestVersion,
            releaseDate,
            daysSinceRelease,
            isAgeOutdated, // Returned separately for "Old" badge in UI
            deviceContext,
        }
    } catch {
        // If we can't parse the versions, return error state
        const errorMessage = `The Doctor is unavailable. Please try again later.`
        return {
            isOutdated: false,
            error: errorMessage,
            latestVersion: undefined,
            releaseDate: undefined,
            daysSinceRelease: undefined,
            isAgeOutdated: false,
            deviceContext: determineDeviceContext(type),
        }
    }
}
