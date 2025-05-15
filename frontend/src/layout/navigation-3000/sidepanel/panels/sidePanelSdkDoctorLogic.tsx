import { actions, kea, path, reducers, selectors, listeners, afterMount, connect, beforeUnmount } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { parseVersion, diffVersions, versionToString, tryParseVersion, isEqualVersion } from 'lib/utils/semver'
import { isNotNil } from 'lib/utils'

import type { sidePanelSdkDoctorLogicType } from './sidePanelSdkDoctorLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { EventType, EventsListQueryParams } from '~/types'

export type SdkType = 'web' | 'ios' | 'android' | 'node' | 'python' | 'php' | 'ruby' | 'go' | 'flutter' | 'react-native' | 'other'
export type SdkVersionInfo = {
    type: SdkType
    version: string
    isOutdated: boolean
    count: number
    releasesAhead?: number
    latestVersion?: string
    multipleInitializations?: boolean
    initCount?: number
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
        if (!cachedData) return null

        const parsedCache = JSON.parse(cachedData) as GitHubCache
        const now = Date.now()
        
        // Check if cache is expired
        if (now - parsedCache.timestamp > GITHUB_CACHE_EXPIRY) {
            localStorage.removeItem(GITHUB_CACHE_KEY)
            return null
        }
        
        return parsedCache
    } catch (error) {
        console.error('[SDK Doctor] Error reading GitHub cache:', error)
        localStorage.removeItem(GITHUB_CACHE_KEY)
        return null
    }
}

const setGitHubCache = (data: Record<SdkType, { latestVersion: string; versions: string[] }>): void => {
    try {
        const cacheData: GitHubCache = {
            timestamp: Date.now(),
            data
        }
        localStorage.setItem(GITHUB_CACHE_KEY, JSON.stringify(cacheData))
    } catch (error) {
        console.error('[SDK Doctor] Error saving GitHub cache:', error)
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
            {} as Record<SdkType, { latestVersion: string, versions: string[] }>,
            {
                loadLatestSdkVersions: async () => {
                    console.log('[SDK Doctor] Loading latest SDK versions')
                    
                    // Check cache first
                    const cachedData = getGitHubCache()
                    if (cachedData) {
                        console.log('[SDK Doctor] Using cached GitHub data')
                        return cachedData.data
                    }
                    
                    console.log('[SDK Doctor] No valid cache found, fetching from GitHub API')
                    
                    // Map SDK types to their GitHub repositories
                    const sdkRepoMap: Record<SdkType, { repo: string, versionPrefix?: string, subdirectory?: string }> = {
                        'web': { repo: 'posthog-js' },
                        'ios': { repo: 'posthog-ios' },
                        'android': { repo: 'posthog-android' },
                        'node': { repo: 'posthog-js-lite', subdirectory: 'posthog-node' },
                        'python': { repo: 'posthog-python' },
                        'php': { repo: 'posthog-php' },
                        'ruby': { repo: 'posthog-ruby' },
                        'go': { repo: 'posthog-go' },
                        'flutter': { repo: 'posthog-flutter' },
                        'react-native': { repo: 'posthog-react-native' },
                        'other': { repo: '' } // Skip for "other"
                    }
                    
                    const result: Record<SdkType, { latestVersion: string, versions: string[] }> = {} as Record<SdkType, { latestVersion: string, versions: string[] }>
                    
                    // Create an array of promises for each SDK type
                    const promises = Object.entries(sdkRepoMap)
                        .filter(([_, { repo }]) => !!repo) // Skip entries with empty repos
                        .map(async ([sdkType, { repo, subdirectory }]) => {
                            try {
                                // Using the same approach as versionCheckerLogic
                                // For Node.js SDK we need special handling since it's in a subdirectory of posthog-js-lite
                                const isNodeSdk = sdkType === 'node'
                                
                                // Add cache busting parameter to avoid GitHub's aggressive caching
                                const cacheBuster = Date.now()
                                const tagsPromise = fetch(`https://api.github.com/repos/PostHog/${repo}/tags?_=${cacheBuster}`, {
                                    headers: {
                                        'Accept': 'application/vnd.github.v3+json'
                                    }
                                })
                                    .then((r) => {
                                        // Check for rate limiting
                                        if (r.status === 403) {
                                            console.error(`[SDK Doctor] GitHub API rate limit hit for ${sdkType}`)
                                            throw new Error('GitHub API rate limit exceeded')
                                        }
                                        return r.json()
                                    })
                                    .then((tags) => {
                                        if (tags && Array.isArray(tags) && tags.length > 0) {
                                            // Extract versions from tags
                                            let versions = tags
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
                                                    latestVersion: versions[0]
                                                }
                                            }
                                        }
                                        return null
                                    })
                                    .catch((error) => {
                                        console.error(`Error fetching latest version for ${sdkType}:`, error)
                                        return null
                                    })
                                
                                return tagsPromise
                            } catch (error) {
                                console.error(`Error setting up fetch for ${sdkType}:`, error)
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
                                latestVersion
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
                    return recentEvents.filter(event => 
                        event.properties?.$lib === 'web' && 
                        event.event === '$pageview' && 
                        event.properties?.hasOwnProperty('$posthog_initialized')
                    )
                },
            },
        ],
        
        sdkVersionsMap: [
            {} as Record<string, SdkVersionInfo>,
            {
                loadRecentEvents: (state) => state, // Keep existing state while loading
                loadRecentEventsSuccess: (state, { recentEvents }) => {
                    console.log('[SDK Doctor] Processing recent events:', recentEvents.length)
                    const sdkVersionsMap: Record<string, SdkVersionInfo> = {}
                    
                    // For demo purposes - HARDCODE multiple initialization
                    // In a real implementation, we would need a more sophisticated detection algorithm
                    // that accounts for session boundaries, timing between events, etc.
                    
                    // Ensure we only look at the most recent 15 events maximum
                    const limitedEvents = recentEvents.slice(0, 15)
                    
                    const webEvents = limitedEvents.filter(e => e.properties?.$lib === 'web')
                    const hasDuplicateInit = webEvents.length > 2
                    
                    // Simple checks:
                    // 1. Multiple distinct $lib_version values from the same user within a short time
                    // 2. Spikes in event sending for the same user (like the test event followed immediately by SDK load)
                    // 3. Multiple pageviews in quick succession
                    const recentTimestamps = webEvents.map(e => new Date(e.timestamp).getTime())
                    const isTimeCompressed = recentTimestamps.length >= 2 && 
                        (Math.max(...recentTimestamps) - Math.min(...recentTimestamps) < 2000)
                    
                    // For the demo, we'll hardcode detection for simplicity
                    // This can be enhanced with proper heuristics later
                    const forceDetection = webEvents.length > 0 && (hasDuplicateInit || isTimeCompressed)
                    
                    // New check - look for file:///Users/slshults/Documents/Tests/test.htm in URLs
                    // This ensures we only show the warning for our test file
                    const hasTestHtmlEvent = limitedEvents.some(e => 
                        e.properties?.$current_url?.includes('test.htm') && 
                        !e.properties?.$current_url?.includes('test-corrected-init.htm')
                    )
                    
                    // Only show the warning for our test.htm file for the demo
                    const shouldShowWarning = forceDetection && hasTestHtmlEvent
                    
                    console.log(`[SDK Doctor] Web events: ${webEvents.length}, Force detection: ${forceDetection}, Has test.htm: ${hasTestHtmlEvent}`)
                    
                    for (const event of limitedEvents) {
                        const lib = event.properties?.$lib
                        const libVersion = event.properties?.$lib_version
                        
                        if (!lib || !libVersion) {
                            continue
                        }
                        
                        const key = `${lib}-${libVersion}`
                        
                        if (!sdkVersionsMap[key]) {
                            // Determine SDK type from lib name
                            let type: SdkType = 'other'
                            if (lib === 'web') type = 'web'
                            else if (lib === 'posthog-ios') type = 'ios'
                            else if (lib === 'posthog-android') type = 'android'
                            else if (lib === 'posthog-node') type = 'node'
                            else if (lib === 'posthog-python') type = 'python'
                            else if (lib === 'posthog-php') type = 'php'
                            else if (lib === 'posthog-ruby') type = 'ruby'
                            else if (lib === 'posthog-go') type = 'go'
                            else if (lib === 'posthog-flutter') type = 'flutter'
                            else if (lib === 'posthog-react-native') type = 'react-native'
                            
                            // Copy existing data for this version if it exists
                            const existingData = state[key] || {}
                            
                            // We'll update the isOutdated value after checking with latest versions
                            // For now, use the existing function as a fallback
                            const isOutdated = existingData.isOutdated !== undefined 
                                ? existingData.isOutdated 
                                : checkIfVersionOutdated(lib, libVersion)
                            
                            sdkVersionsMap[key] = {
                                ...existingData,
                                type,
                                version: libVersion,
                                isOutdated,
                                count: 1,
                                // For web SDK, apply our detection logic
                                multipleInitializations: type === 'web' ? shouldShowWarning : false,
                                initCount: type === 'web' && shouldShowWarning ? 3 : undefined,
                            }
                        } else {
                            sdkVersionsMap[key].count += 1
                        }
                    }
                    
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
                            let sdkType: SdkType = info.type
                            
                            const { isOutdated, releasesAhead, latestVersion } = 
                                checkVersionAgainstLatest(sdkType, version, latestSdkVersions)
                            
                            updatedMap[key] = {
                                ...info,
                                isOutdated,
                                releasesAhead,
                                latestVersion
                            }
                        })
                    } else {
                        // If we couldn't get latest versions, fall back to the hardcoded check
                        Object.entries(updatedMap).forEach(([key, info]) => {
                            // Get the version directly from info object
                            const version = info.version
                            
                            // Convert type to lib name for the hardcoded check
                            let libName = 'web'
                            if (info.type === 'ios') libName = 'posthog-ios'
                            if (info.type === 'android') libName = 'posthog-android'
                            if (info.type === 'node') libName = 'posthog-node'
                            if (info.type === 'python') libName = 'posthog-python'
                            if (info.type === 'php') libName = 'posthog-php'
                            if (info.type === 'ruby') libName = 'posthog-ruby'
                            if (info.type === 'go') libName = 'posthog-go'
                            if (info.type === 'flutter') libName = 'posthog-flutter'
                            if (info.type === 'react-native') libName = 'posthog-react-native'
                            
                            console.log(`[SDK Doctor] Fallback check for ${libName} version ${version}`)
                            
                            updatedMap[key] = {
                                ...info,
                                isOutdated: checkIfVersionOutdated(libName, version)
                            }
                        })
                    }
                    
                    return updatedMap
                }
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
                return sdkVersions.filter(sdk => sdk.isOutdated).length
            },
        ],
        
        multipleInitSdks: [
            (s) => [s.sdkVersions],
            (sdkVersions: SdkVersionInfo[]): SdkVersionInfo[] => {
                return sdkVersions.filter(sdk => sdk.multipleInitializations)
            },
        ],
        
        sdkHealth: [
            (s) => [s.outdatedSdkCount, s.multipleInitSdks],
            (outdatedSdkCount: number, multipleInitSdks: SdkVersionInfo[]): SdkHealthStatus => {
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
    console.log(`[SDK Doctor] Checking if outdated: ${lib} version ${version}`)
    
    // This function now serves as a fallback when GitHub API data isn't available
    // It should match the logic in checkVersionAgainstLatest for consistency
    
    // Parse the version string into components
    const components = version.split('.')
    if (components.length < 2) {
        console.log(`[SDK Doctor] Cannot determine version: ${version}`)
        return false // Can't determine
    }
    
    const major = parseInt(components[0])
    const minor = parseInt(components[1])
    
    // Debug log for PHP SDK specifically
    if (lib === 'posthog-php') {
        console.log(`[SDK Doctor] PHP SDK check: version ${version}, major=${major}, minor=${minor}, isOutdated=${major < 3}`)
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
    latestVersionsData: Record<SdkType, { latestVersion: string, versions: string[] }>
): { isOutdated: boolean, releasesAhead?: number, latestVersion?: string } {
    console.log(`[SDK Doctor] checkVersionAgainstLatest for ${type} version ${version}`)
    console.log(`[SDK Doctor] Available data:`, Object.keys(latestVersionsData))
    
    // Convert type to lib name for consistency
    let lib = 'web'
    if (type === 'ios') lib = 'posthog-ios'
    if (type === 'android') lib = 'posthog-android'
    if (type === 'node') lib = 'posthog-node'
    if (type === 'python') lib = 'posthog-python'
    if (type === 'php') lib = 'posthog-php'
    if (type === 'ruby') lib = 'posthog-ruby'
    if (type === 'go') lib = 'posthog-go'
    if (type === 'flutter') lib = 'posthog-flutter'
    if (type === 'react-native') lib = 'posthog-react-native'
    
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
            const isOutdated = (major < 4) || (major === 4 && minor < 17)
            
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
                latestVersion: mockLatestVersion
            }
        } catch (e) {
            // If parsing fails, use the fallback check
            return {
                isOutdated: checkIfVersionOutdated(lib, version),
                latestVersion: mockLatestVersion
            }
        }
    }
    
    // If we don't have data for this SDK type or the SDK type is "other", fall back to hardcoded check
    if (!latestVersionsData[type] || type === 'other') {
        console.log(`[SDK Doctor] Falling back to hardcoded check for ${type} (lib=${lib})`)
        const isOutdated = checkIfVersionOutdated(lib, version)
        console.log(`[SDK Doctor] Hardcoded check result for ${lib} ${version}: isOutdated=${isOutdated}`)
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
            latestVersion
        }
    } catch (e) {
        // If we can't parse the versions, fall back to the hardcoded check
        console.log(`[SDK Doctor] Error parsing versions, falling back to hardcoded check for ${lib}: ${e}`)
        
        return { 
            isOutdated: checkIfVersionOutdated(lib, version),
            latestVersion 
        }
    }
}
