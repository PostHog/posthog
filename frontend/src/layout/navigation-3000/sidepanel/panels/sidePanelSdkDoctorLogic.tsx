/* oxlint-disable no-console */
import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
// import { isNotNil } from 'lib/utils' // Unused after bulk fetching removal
import { getAppContext } from 'lib/utils/getAppContext'
import { diffVersions, parseVersion } from 'lib/utils/semver'
// Removed tryParseVersion (unused after bulk fetching removal)
import { teamLogic } from 'scenes/teamLogic'

import { EventType, EventsListQueryParams } from '~/types'

import type { sidePanelSdkDoctorLogicType } from './sidePanelSdkDoctorLogicType'

// Debug mode detection following PostHog's standard pattern
const IS_DEBUG_MODE = (() => {
    const appContext = getAppContext()
    return appContext?.preflight?.is_debug || process.env.NODE_ENV === 'test'
})()

// TODO: Multi-init detection temporarily disabled for post-MVP
// Global cache for GitHub releases data
// let releasesCache: { data: any[] | null; timestamp: number } = { data: null, timestamp: 0 }

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
    | 'dotnet'
    | 'elixir'
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

    // NEW: Age-based tracking
    releaseDate?: string // ISO date string when this version was released
    daysSinceRelease?: number // Calculated days since release
    isAgeOutdated?: boolean // True if >8 weeks old AND newer releases exist

    // NEW: Device context
    deviceContext?: 'mobile' | 'desktop' | 'mixed' // Based on detected usage patterns
    eventVolume?: 'low' | 'medium' | 'high' // Based on event count
    lastSeenTimestamp?: string // ISO timestamp of most recent event

    // Error handling
    error?: string // Error message when SDK Doctor is unavailable
}

// NEW: Device context detection configuration
export type DeviceContextConfig = {
    mobileSDKs: SdkType[] // ['ios', 'android', 'flutter', 'react-native']
    desktopSDKs: SdkType[] // ['web', 'node', 'python', 'php', 'ruby', 'go', 'dotnet', 'elixir']
    volumeThresholds: {
        low: number // < 10 events
        medium: number // 10-50 events
        high: number // > 50 events
    }
    ageThresholds: {
        warnAfterWeeks: number // 8 weeks
        criticalAfterWeeks: number // 16 weeks
    }
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
    exampleEventId?: string // UUID of a problematic event (kept for backwards compatibility)
    exampleEventTimestamp?: string // timestamp of the problematic event (kept for backwards compatibility)
    flagExampleEvents: Record<string, { eventId: string; timestamp: string }> // per-flag example events
    sessionCount: number
}

export type SdkHealthStatus = 'healthy' | 'warning' | 'critical'

// Client-side caching removed - now handled server-side with Redis

// DISABLED: Bulk GitHub API functions (causing 403 errors) - kept for future per-SDK implementation
/*
const fetchGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        const response = await fetch('https://api.github.com/repos/PostHog/posthog-js/releases?per_page=100')
        if (!response.ok) {
            throw new Error(`GitHub API error: ${response.status}`)
        }

        const releases = await response.json()
        const releaseDates: Record<string, string> = {}

        // Filter for posthog-js releases and extract version + date
        releases
            .filter((release: any) => release.tag_name?.startsWith('posthog-js@'))
            .forEach((release: any) => {
                const version = release.tag_name.replace('posthog-js@', '')
                releaseDates[version] = release.published_at
            })

        console.info(`[SDK Doctor] Fetched ${Object.keys(releaseDates).length} Web SDK release dates from GitHub API`)
        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch Web SDK GitHub release dates:', error)
        return {}
    }
}

// Fetch Python SDK release dates from GitHub Releases API for time-based detection
const fetchPythonGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        const response = await fetch('https://api.github.com/repos/PostHog/posthog-python/releases?per_page=100')
        if (!response.ok) {
            throw new Error(`GitHub API error: ${response.status}`)
        }

        const releases = await response.json()
        const releaseDates: Record<string, string> = {}

        // Python releases use version tags like "v6.7.4"
        releases
            .filter((release: any) => release.tag_name?.match(/^v?\d+\.\d+\.\d+$/))
            .forEach((release: any) => {
                const version = release.tag_name.replace(/^v/, '') // Remove "v" prefix if present
                releaseDates[version] = release.published_at
            })

        console.info(
            `[SDK Doctor] Fetched ${Object.keys(releaseDates).length} Python SDK release dates from GitHub API`
        )
        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch Python SDK GitHub release dates:', error)
        return {}
    }
}

// Fetch React Native SDK release dates from GitHub Releases API for time-based detection
const fetchReactNativeGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        const response = await fetch('https://api.github.com/repos/PostHog/posthog-js/releases?per_page=100')
        if (!response.ok) {
            throw new Error(`GitHub API error: ${response.status}`)
        }

        const releases = await response.json()
        const releaseDates: Record<string, string> = {}

        // React Native releases use version tags like "posthog-react-native@4.5.1"
        const reactNativeReleases = releases.filter((release: any) =>
            release.tag_name?.startsWith('posthog-react-native@')
        )

        reactNativeReleases.forEach((release: any) => {
            const version = release.tag_name.replace('posthog-react-native@', '')
            releaseDates[version] = release.published_at
        })

        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch React Native SDK GitHub release dates:', error)
        return {}
    }
}

// Fetch Flutter SDK release dates from GitHub Releases API for time-based detection
const fetchFlutterGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        const response = await fetch('https://api.github.com/repos/PostHog/posthog-flutter/releases?per_page=100')
        if (!response.ok) {
            throw new Error(`GitHub API error: ${response.status}`)
        }

        const releases = await response.json()
        const releaseDates: Record<string, string> = {}

        // Flutter releases use simple semantic version tags like "5.5.0"
        releases.forEach((release: any) => {
            if (release.tag_name && /^\d+\.\d+\.\d+$/.test(release.tag_name)) {
                releaseDates[release.tag_name] = release.published_at
            }
        })

        console.info(
            `[SDK Doctor] Fetched ${Object.keys(releaseDates).length} Flutter SDK release dates from GitHub API`
        )
        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch Flutter SDK GitHub release dates:', error)
        return {}
    }
}

// Fetch iOS SDK release dates from GitHub Releases API for time-based detection
const fetchiOSGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        const response = await fetch('https://api.github.com/repos/PostHog/posthog-ios/releases?per_page=100')
        if (!response.ok) {
            throw new Error(`GitHub API error: ${response.status}`)
        }

        const releases = await response.json()
        const releaseDates: Record<string, string> = {}

        // iOS releases use simple semantic version tags like "3.30.1"
        releases.forEach((release: any) => {
            if (release.tag_name && /^\d+\.\d+\.\d+$/.test(release.tag_name)) {
                releaseDates[release.tag_name] = release.published_at
            }
        })

        console.info(
            `[SDK Doctor] Fetched ${Object.keys(releaseDates).length} iOS SDK release dates from GitHub API`
        )
        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch iOS SDK GitHub release dates:', error)
        return {}
    }
}

// Fetch Android SDK release dates from GitHub Releases API for time-based detection
const fetchAndroidGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        console.info('[SDK Doctor] Starting Android GitHub API fetch...')
        const response = await fetch('https://api.github.com/repos/PostHog/posthog-android/releases?per_page=100')
        console.info(`[SDK Doctor] Android GitHub API response status: ${response.status}`)

        if (!response.ok) {
            throw new Error(`GitHub API error: ${response.status}`)
        }

        const releases = await response.json()
        console.info(`[SDK Doctor] Android GitHub API returned ${releases.length} releases`)
        const releaseDates: Record<string, string> = {}

        // Android releases use simple semantic version tags like "3.20.2"
        releases.forEach((release: any) => {
            if (release.tag_name && /^\d+\.\d+\.\d+$/.test(release.tag_name)) {
                releaseDates[release.tag_name] = release.published_at
                console.info(`[SDK Doctor] Android: ${release.tag_name} -> ${release.published_at}`)
            }
        })

        console.info(
            `[SDK Doctor] Fetched ${Object.keys(releaseDates).length} Android SDK release dates from GitHub API`
        )
        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch Android SDK GitHub release dates:', error)
        return {}
    }
}

// Fetch Ruby SDK release dates from GitHub Releases API for time-based detection
const fetchRubyGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        const response = await fetch('https://api.github.com/repos/PostHog/posthog-ruby/releases?per_page=100')
        if (!response.ok) {
            throw new Error(`GitHub API error: ${response.status}`)
        }

        const releases = await response.json()
        const releaseDates: Record<string, string> = {}

        // Ruby releases use simple semantic version tags like "3.1.2"
        releases.forEach((release: any) => {
            if (release.tag_name && /^\d+\.\d+\.\d+$/.test(release.tag_name)) {
                releaseDates[release.tag_name] = release.published_at
            }
        })

        console.info(
            `[SDK Doctor] Fetched ${Object.keys(releaseDates).length} Ruby SDK release dates from GitHub API`
        )
        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch Ruby SDK GitHub release dates:', error)
        return {}
    }
}
*/

// Fetch Node.js SDK release dates from GitHub Releases API for time-based detection
const fetchNodeGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        const response = await fetch('https://api.github.com/repos/PostHog/posthog-js/releases?per_page=100')
        if (!response.ok) {
            throw new Error(`GitHub API error: ${response.status}`)
        }

        const releases = await response.json()
        const releaseDates: Record<string, string> = {}

        // Node.js releases use version tags like "posthog-node@5.6.0"
        const nodeReleases = releases.filter((release: any) => release.tag_name?.startsWith('posthog-node@'))

        nodeReleases.forEach((release: any) => {
            const version = release.tag_name.replace('posthog-node@', '')
            releaseDates[version] = release.published_at
        })

        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch Node.js SDK GitHub release dates:', error)
        return {}
    }
}

// NEW: Fetch individual SDK data on-demand with per-SDK caching
const fetchSdkData = async (
    sdkType: SdkType
): Promise<{ latestVersion: string; versions: string[]; releaseDates?: Record<string, string> } | null> => {
    // Check server cache first
    if (IS_DEBUG_MODE) {
        console.info(
            `[SDK Doctor] Checking if ${sdkType.charAt(0).toUpperCase() + sdkType.slice(1)} SDK info is cached on server...`
        )
    }
    try {
        const response = await api.get(`api/github-sdk-versions/${sdkType}`)
        if (response.latestVersion && response.versions) {
            if (IS_DEBUG_MODE) {
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
            }
            return {
                latestVersion: response.latestVersion,
                versions: response.versions,
                releaseDates: response.releaseDates || {},
            }
        }
    } catch {
        if (IS_DEBUG_MODE) {
            console.info(
                `[SDK Doctor] ${sdkType.charAt(0).toUpperCase() + sdkType.slice(1)} SDK info not found in CACHE, querying GitHub API`
            )
        }
    }

    // Implement per-SDK fetching for all time-based detection SDKs
    if (
        ![
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
        if (IS_DEBUG_MODE) {
            console.info(`[SDK Doctor] Per-SDK fetch not implemented for ${sdkType} yet`)
        }
        return null
    }

    try {
        console.info(`[SDK Doctor] fetchSdkData() called for ${sdkType} - fetching fresh data...`)

        let changelogUrl: string
        let versionRegex: RegExp
        let githubFetcher: () => Promise<Record<string, string>>

        // Configure per-SDK parameters
        switch (sdkType) {
            case 'web':
                changelogUrl = 'https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/browser/CHANGELOG.md'
                versionRegex = /^## (\d+\.\d+\.\d+)$/gm
                githubFetcher = async () => {
                    const response = await fetch(
                        'https://api.github.com/repos/PostHog/posthog-js/releases?per_page=100'
                    )
                    if (!response.ok) {
                        throw new Error(`GitHub API error: ${response.status}`)
                    }
                    const releases = await response.json()
                    const releaseDates: Record<string, string> = {}
                    releases
                        .filter((r: any) => r.tag_name?.startsWith('posthog-js@'))
                        .forEach((r: any) => {
                            const version = r.tag_name.replace('posthog-js@', '')
                            releaseDates[version] = r.published_at
                        })
                    return releaseDates
                }
                break

            case 'python':
                // Python SDK has special handling - dates are in CHANGELOG.md
                const pythonChangelogResponse = await fetch(
                    'https://raw.githubusercontent.com/PostHog/posthog-python/master/CHANGELOG.md'
                )
                if (!pythonChangelogResponse.ok) {
                    throw new Error(`Failed to fetch Python CHANGELOG.md: ${pythonChangelogResponse.status}`)
                }
                const pythonChangelogText = await pythonChangelogResponse.text()

                // Extract versions and dates from CHANGELOG.md format: # 6.7.5 - 2025-09-16
                const pythonMatches = [...pythonChangelogText.matchAll(/^# (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})/gm)]
                const pythonVersions = pythonMatches.map((match) => match[1])
                const pythonReleaseDates: Record<string, string> = {}

                pythonMatches.forEach((match) => {
                    const version = match[1]
                    const dateStr = match[2] + 'T00:00:00Z' // Convert YYYY-MM-DD to ISO format
                    pythonReleaseDates[version] = dateStr
                })

                const pythonResult = {
                    latestVersion: pythonVersions[0],
                    versions: pythonVersions,
                    releaseDates: pythonReleaseDates,
                }

                console.info(
                    `[SDK Doctor] Python SDK complete result: latestVersion=${pythonResult.latestVersion}, release dates count=${Object.keys(pythonResult.releaseDates).length}`
                )

                // Return result (server handles caching)
                return pythonResult

            case 'node':
                changelogUrl = 'https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/node/CHANGELOG.md'
                versionRegex = /^## (\d+\.\d+\.\d+)$/gm
                githubFetcher = async () => {
                    // First try to get release dates from PR links in CHANGELOG.md
                    const changelogResponse = await fetch(
                        'https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/node/CHANGELOG.md'
                    )
                    if (!changelogResponse.ok) {
                        throw new Error(`Failed to fetch Node.js CHANGELOG.md: ${changelogResponse.status}`)
                    }
                    const changelogText = await changelogResponse.text()

                    const releaseDates: Record<string, string> = {}

                    // Extract version sections with their PR links
                    const versionSections = changelogText.split(/^## (\d+\.\d+\.\d+)$/gm)

                    for (let i = 1; i < versionSections.length; i += 2) {
                        const version = versionSections[i]
                        const content = versionSections[i + 1]

                        // Extract first PR link: [#2346](https://github.com/PostHog/posthog-js/pull/2346)
                        const prMatch = content.match(
                            /\[#(\d+)\]\(https:\/\/github\.com\/PostHog\/posthog-js\/pull\/(\d+)\)/
                        )

                        if (prMatch) {
                            const prNumber = prMatch[2]
                            try {
                                // Fetch PR merge date from GitHub API
                                const prResponse = await fetch(
                                    `https://api.github.com/repos/PostHog/posthog-js/pulls/${prNumber}`
                                )
                                if (prResponse.ok) {
                                    const prData = await prResponse.json()
                                    if (prData.merged_at) {
                                        releaseDates[version] = prData.merged_at
                                        console.info(
                                            `[SDK Doctor] Node.js ${version} -> ${prData.merged_at} (from PR #${prNumber})`
                                        )
                                    }
                                }
                            } catch (error) {
                                console.warn(
                                    `[SDK Doctor] Failed to fetch PR #${prNumber} for Node.js ${version}:`,
                                    error
                                )
                            }

                            // Add delay to avoid rate limiting
                            await new Promise((resolve) => setTimeout(resolve, 100))
                        }
                    }

                    // Fallback to GitHub releases API for versions without PR links
                    try {
                        const githubReleaseDates = await fetchNodeGitHubReleaseDates()
                        for (const [version, date] of Object.entries(githubReleaseDates)) {
                            if (!releaseDates[version] && typeof date === 'string') {
                                releaseDates[version] = date
                                console.info(
                                    `[SDK Doctor] Node.js ${version} -> ${date} (from GitHub releases API fallback)`
                                )
                            }
                        }
                    } catch (error) {
                        console.warn('[SDK Doctor] GitHub releases API fallback failed for Node.js:', error)
                    }

                    console.info(
                        `[SDK Doctor] Fetched ${Object.keys(releaseDates).length} Node.js version dates (PR links + GitHub releases fallback)`
                    )
                    return releaseDates
                }
                break

            case 'react-native':
                changelogUrl =
                    'https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/react-native/CHANGELOG.md'
                versionRegex = /^## (\d+\.\d+\.\d+)$/gm
                githubFetcher = async () => {
                    const response = await fetch(
                        'https://api.github.com/repos/PostHog/posthog-js/releases?per_page=100'
                    )
                    if (!response.ok) {
                        throw new Error(`GitHub API error: ${response.status}`)
                    }
                    const releases = await response.json()
                    const releaseDates: Record<string, string> = {}
                    releases
                        .filter((r: any) => r.tag_name?.startsWith('posthog-react-native@'))
                        .forEach((r: any) => {
                            const version = r.tag_name.replace('posthog-react-native@', '')
                            releaseDates[version] = r.published_at
                        })
                    return releaseDates
                }
                break

            case 'flutter':
                changelogUrl = 'https://raw.githubusercontent.com/PostHog/posthog-flutter/main/CHANGELOG.md'
                versionRegex = /^## (\d+\.\d+\.\d+)$/gm
                githubFetcher = async () => {
                    const response = await fetch(
                        'https://api.github.com/repos/PostHog/posthog-flutter/releases?per_page=100'
                    )
                    if (!response.ok) {
                        throw new Error(`GitHub API error: ${response.status}`)
                    }
                    const releases = await response.json()
                    const releaseDates: Record<string, string> = {}
                    releases.forEach((r: any) => {
                        if (r.tag_name && /^\d+\.\d+\.\d+$/.test(r.tag_name)) {
                            releaseDates[r.tag_name] = r.published_at
                        }
                    })
                    return releaseDates
                }
                break

            case 'ios':
                // iOS SDK has special handling - dates are in CHANGELOG.md
                const iosChangelogResponse = await fetch(
                    'https://raw.githubusercontent.com/PostHog/posthog-ios/main/CHANGELOG.md'
                )
                if (!iosChangelogResponse.ok) {
                    throw new Error(`Failed to fetch iOS CHANGELOG.md: ${iosChangelogResponse.status}`)
                }
                const iosChangelogText = await iosChangelogResponse.text()

                // Extract versions and dates from CHANGELOG.md format: ## 3.31.0 - 2025-08-29
                const iosMatches = [...iosChangelogText.matchAll(/^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})/gm)]
                const iosVersions = iosMatches.map((match) => match[1])
                const iosReleaseDates: Record<string, string> = {}

                iosMatches.forEach((match) => {
                    const version = match[1]
                    const dateStr = match[2] + 'T00:00:00Z' // Convert YYYY-MM-DD to ISO format
                    iosReleaseDates[version] = dateStr
                })

                const iosResult = {
                    latestVersion: iosVersions[0],
                    versions: iosVersions,
                    releaseDates: iosReleaseDates,
                }

                console.info(
                    `[SDK Doctor] iOS SDK complete result: latestVersion=${iosResult.latestVersion}, release dates count=${Object.keys(iosResult.releaseDates).length}`
                )

                // Return result
                return iosResult

            case 'android':
                // Android SDK has special handling - dates are in CHANGELOG.md
                const androidChangelogResponse = await fetch(
                    'https://raw.githubusercontent.com/PostHog/posthog-android/main/CHANGELOG.md'
                )
                if (!androidChangelogResponse.ok) {
                    throw new Error(`Failed to fetch Android CHANGELOG.md: ${androidChangelogResponse.status}`)
                }
                const androidChangelogText = await androidChangelogResponse.text()

                // Extract versions and dates from CHANGELOG.md format: ## 3.21.3 - 2025-09-16
                const androidMatches = [...androidChangelogText.matchAll(/^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})/gm)]
                const androidVersions = androidMatches.map((match) => match[1])
                const androidReleaseDates: Record<string, string> = {}

                androidMatches.forEach((match) => {
                    const version = match[1]
                    const dateStr = match[2] + 'T00:00:00Z' // Convert YYYY-MM-DD to ISO format
                    androidReleaseDates[version] = dateStr
                })

                const androidResult = {
                    latestVersion: androidVersions[0],
                    versions: androidVersions,
                    releaseDates: androidReleaseDates,
                }

                console.info(
                    `[SDK Doctor] Android SDK complete result: latestVersion=${androidResult.latestVersion}, release dates count=${Object.keys(androidResult.releaseDates).length}`
                )

                // Return result
                return androidResult

            case 'php':
                // PHP SDK has special format in History.md: "3.7.0 / 2025-08-26"
                const phpHistoryResponse = await fetch(
                    'https://raw.githubusercontent.com/PostHog/posthog-php/master/History.md'
                )
                if (!phpHistoryResponse.ok) {
                    throw new Error(`Failed to fetch PHP History.md: ${phpHistoryResponse.status}`)
                }
                const phpHistoryText = await phpHistoryResponse.text()

                // Extract versions from History.md (format: "3.7.0 / 2025-08-26")
                const phpVersions: string[] = []
                const phpReleaseDates: Record<string, string> = {}

                // Split by lines and process each line
                const lines = phpHistoryText.split('\n')
                for (const line of lines) {
                    const match = line.match(/^(\d+\.\d+\.\d+)\s*\/\s*(\d{4}-\d{2}-\d{2})/)
                    if (match) {
                        const [, version, date] = match
                        phpVersions.push(version)
                        phpReleaseDates[version] = `${date}T00:00:00Z`
                    }
                }

                if (phpVersions.length === 0) {
                    throw new Error('No PHP versions found in History.md')
                }

                const phpResult = {
                    latestVersion: phpVersions[0],
                    versions: phpVersions,
                    releaseDates: phpReleaseDates,
                }

                console.info(
                    `[SDK Doctor] PHP SDK complete result: latestVersion=${phpResult.latestVersion}, versions count=${phpVersions.length}, versions=${phpVersions.slice(0, 5).join(', ')}`
                )
                console.info(`[SDK Doctor] PHP SDK setting cache and returning result for 'php' type`)

                // Return result
                return phpResult

            case 'elixir':
                // Elixir SDK has format in CHANGELOG.md: "## 1.1.0 - 2025-07-01"
                const elixirChangelogResponse = await fetch(
                    'https://raw.githubusercontent.com/PostHog/posthog-elixir/master/CHANGELOG.md'
                )
                if (!elixirChangelogResponse.ok) {
                    throw new Error(`Failed to fetch Elixir CHANGELOG.md: ${elixirChangelogResponse.status}`)
                }
                const elixirChangelogText = await elixirChangelogResponse.text()
                // Extract versions from CHANGELOG.md (format: "## 1.1.0 - 2025-07-01")
                const elixirVersions: string[] = []
                const elixirReleaseDates: Record<string, string> = {}
                // Parse version entries with date format
                const elixirMatches = [...elixirChangelogText.matchAll(/^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})/gm)]
                elixirMatches.forEach((match) => {
                    const [, version, date] = match
                    elixirVersions.push(version)
                    elixirReleaseDates[version] = `${date}T00:00:00Z`
                })
                if (elixirVersions.length === 0) {
                    throw new Error('No Elixir versions found in CHANGELOG.md')
                }
                const elixirResult = {
                    latestVersion: elixirVersions[0],
                    versions: elixirVersions,
                    releaseDates: elixirReleaseDates,
                }
                console.info(
                    `[SDK Doctor] Elixir SDK complete result: latestVersion=${elixirResult.latestVersion}, versions count=${elixirVersions.length}, versions=${elixirVersions.slice(0, 5).join(', ')}`
                )
                console.info(`[SDK Doctor] Elixir SDK setting cache and returning result for 'elixir' type`)
                // Return result
                return elixirResult

            case 'dotnet':
                // .NET SDK uses GitHub Releases (format: "v2.0.0")
                const dotnetReleasesResponse = await fetch(
                    'https://api.github.com/repos/PostHog/posthog-dotnet/releases?per_page=100'
                )
                if (!dotnetReleasesResponse.ok) {
                    throw new Error(`Failed to fetch .NET GitHub releases: ${dotnetReleasesResponse.status}`)
                }
                const dotnetReleases = await dotnetReleasesResponse.json()
                // Extract versions from GitHub releases (format: "v2.0.0")
                const dotnetVersions: string[] = []
                const dotnetReleaseDates: Record<string, string> = {}
                // Parse releases and extract semantic versions
                dotnetReleases.forEach((release: any) => {
                    if (release.tag_name && release.tag_name.startsWith('v')) {
                        const version = release.tag_name.replace('v', '')
                        if (/^\d+\.\d+\.\d+$/.test(version)) {
                            // Only semantic versions
                            dotnetVersions.push(version)
                            dotnetReleaseDates[version] = release.published_at
                        }
                    }
                })
                if (dotnetVersions.length === 0) {
                    throw new Error('No .NET versions found in GitHub releases')
                }
                const dotnetResult = {
                    latestVersion: dotnetVersions[0],
                    versions: dotnetVersions,
                    releaseDates: dotnetReleaseDates,
                }
                console.info(
                    `[SDK Doctor] .NET SDK complete result: latestVersion=${dotnetResult.latestVersion}, versions count=${dotnetVersions.length}, versions=${dotnetVersions.slice(0, 5).join(', ')}`
                )
                console.info(`[SDK Doctor] .NET SDK setting cache and returning result for 'dotnet' type`)
                // Return result
                return dotnetResult

            case 'ruby':
                changelogUrl = 'https://raw.githubusercontent.com/PostHog/posthog-ruby/master/CHANGELOG.md'
                versionRegex = /^## (\d+\.\d+\.\d+)/gm
                githubFetcher = async () => {
                    const response = await fetch(
                        'https://api.github.com/repos/PostHog/posthog-ruby/releases?per_page=100'
                    )
                    if (!response.ok) {
                        throw new Error(`GitHub API error: ${response.status}`)
                    }
                    const releases = await response.json()
                    const releaseDates: Record<string, string> = {}
                    releases.forEach((r: any) => {
                        if (r.tag_name && /^\d+\.\d+\.\d+$/.test(r.tag_name)) {
                            releaseDates[r.tag_name] = r.published_at
                        }
                    })
                    return releaseDates
                }
                break

            case 'go':
                // Go SDK has special handling - fetch everything in one go
                const goChangelogResponse = await fetch(
                    'https://raw.githubusercontent.com/PostHog/posthog-go/master/CHANGELOG.md'
                )
                if (!goChangelogResponse.ok) {
                    throw new Error(`Failed to fetch Go CHANGELOG.md: ${goChangelogResponse.status}`)
                }
                const goChangelogText = await goChangelogResponse.text()

                // Extract versions from CHANGELOG.md
                const goVersionMatches = goChangelogText.match(/^## (\d+\.\d+\.\d+)$/gm)
                if (!goVersionMatches) {
                    throw new Error('No Go versions found in CHANGELOG.md')
                }
                const goVersions = goVersionMatches
                    .map((match) => match.replace(/^## /, ''))
                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v))

                // Fetch release dates
                const goReleaseDates = await fetchGoGitHubReleaseDates()

                const goResult = {
                    latestVersion: goVersions[0],
                    versions: goVersions,
                    releaseDates: goReleaseDates,
                }

                console.info(
                    `[SDK Doctor] Go SDK complete result: latestVersion=${goResult.latestVersion}, release dates count=${Object.keys(goResult.releaseDates).length}`
                )

                // Return result
                return goResult

            default:
                throw new Error(`Unsupported SDK type: ${sdkType}`)
        }

        // Fetch CHANGELOG.md data
        const changelogResponse = await fetch(changelogUrl)
        if (!changelogResponse.ok) {
            throw new Error(`Failed to fetch CHANGELOG.md: ${changelogResponse.status}`)
        }
        const changelogText = await changelogResponse.text()

        // Extract versions
        const versionMatches = changelogText.match(versionRegex)
        if (!versionMatches) {
            throw new Error(`No versions found in CHANGELOG.md for ${sdkType}`)
        }

        const versions = versionMatches
            .map((match) => match.replace(/^## /, '')) // Remove "## " prefix
            .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

        if (versions.length === 0) {
            throw new Error(`No valid versions found for ${sdkType}`)
        }

        // Fetch GitHub release dates for time-based detection
        console.info(`[SDK Doctor] Calling GitHub fetcher for ${sdkType}...`)
        const releaseDates = await githubFetcher()
        console.info(`[SDK Doctor] GitHub fetcher returned ${Object.keys(releaseDates).length} dates for ${sdkType}`)

        const result = {
            latestVersion: versions[0],
            versions: versions,
            releaseDates,
        }

        console.info(
            `[SDK Doctor] fetchSdkData() returning for ${sdkType}: latestVersion=${result.latestVersion}, release dates count=${Object.keys(result.releaseDates).length}`
        )

        // Return result (server handles caching)
        return result
    } catch (error) {
        console.warn(`[SDK Doctor] Failed to fetch ${sdkType} data:`, error)
        return null
    }
}

// Fetch Go SDK release dates by following the "Full changelog" links from CHANGELOG.md
const fetchGoGitHubReleaseDates = async (): Promise<Record<string, string>> => {
    try {
        console.info('[SDK Doctor] Starting Go SDK release date fetch via Full changelog links...')

        // First, get the CHANGELOG.md to extract the Full changelog links
        const changelogResponse = await fetch(
            'https://raw.githubusercontent.com/PostHog/posthog-go/master/CHANGELOG.md'
        )
        if (!changelogResponse.ok) {
            console.error('[SDK Doctor] Failed to fetch Go CHANGELOG.md:', changelogResponse.status)
            throw new Error(`Failed to fetch CHANGELOG.md: ${changelogResponse.status}`)
        }

        const changelogText = await changelogResponse.text()
        console.info('[SDK Doctor] Go CHANGELOG.md fetched, length:', changelogText.length)
        const releaseDates: Record<string, string> = {}

        // Extract just the latest ~5 versions and their Full Changelog links
        // Pattern: ## 1.6.8 followed by * [Full Changelog](https://github.com/PostHog/posthog-go/compare/v1.6.7...v1.6.8)
        const versionPattern = /^## (\d+\.\d+\.\d+)\s*\n[\s\S]*?\* \[Full Changelog\]\(([^)]+)\)/gm
        const matches = [...changelogText.matchAll(versionPattern)]

        console.info(`[SDK Doctor] Found Go version entries: ${matches.length}`)

        // Only process the latest 5 versions to avoid excessive API calls
        const latestMatches = matches.slice(0, 5)
        console.info(`[SDK Doctor] Processing latest ${latestMatches.length} Go versions`)

        for (const match of latestMatches) {
            const version = match[1]
            const compareUrl = match[2]

            console.info(`[SDK Doctor] Go version ${version}, compare URL: ${compareUrl}`)

            try {
                // Extract the target tag from the compare URL
                // e.g., https://github.com/PostHog/posthog-go/compare/v1.6.7...v1.6.8 -> v1.6.8
                const targetTagMatch = compareUrl.match(/\.\.\.(.+)$/)

                if (targetTagMatch) {
                    const targetTag = targetTagMatch[1]
                    console.info(`[SDK Doctor] Fetching date for Go ${version} via tag ${targetTag}`)

                    // Fetch the tag information from GitHub API
                    const tagResponse = await fetch(
                        `https://api.github.com/repos/PostHog/posthog-go/git/refs/tags/${targetTag}`
                    )

                    if (tagResponse.ok) {
                        const tagData = await tagResponse.json()
                        const commitSha = tagData.object?.sha

                        if (commitSha) {
                            // Fetch the commit details to get the date
                            const commitResponse = await fetch(
                                `https://api.github.com/repos/PostHog/posthog-go/commits/${commitSha}`
                            )

                            if (commitResponse.ok) {
                                const commitData = await commitResponse.json()
                                const commitDate = commitData.commit?.author?.date || commitData.commit?.committer?.date

                                if (commitDate) {
                                    releaseDates[version] = commitDate
                                    console.info(`[SDK Doctor] ✅ Go ${version} -> ${commitDate}`)
                                }
                            }
                        }
                    }
                }
            } catch (error) {
                console.warn(`[SDK Doctor] Failed to fetch date for Go version ${version}:`, error)
            }

            // Shorter delay since we're only processing 5 versions
            await new Promise((resolve) => setTimeout(resolve, 100))
        }

        console.info(
            `[SDK Doctor] Fetched ${Object.keys(releaseDates).length} Go SDK version dates via Full changelog links`
        )
        console.info('[SDK Doctor] Go release dates object:', JSON.stringify(releaseDates))

        return releaseDates
    } catch (error) {
        console.warn('[SDK Doctor] Failed to fetch Go SDK release dates via Full changelog:', error)
        return {}
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
        updateSdkVersionsMap: (updatedMap: Record<string, SdkVersionInfo>) => ({ updatedMap }),
    }),

    loaders(({ values }) => ({
        recentEvents: [
            [] as EventType[],
            {
                loadRecentEvents: async () => {
                    const teamId = values.currentTeamId || undefined
                    try {
                        // Simplified approach: get strategy based on demo mode vs production
                        const strategy = determineSamplingStrategy(0) // Let the function handle demo mode

                        // Fetch events with strategy-based parameters
                        const params: EventsListQueryParams = {
                            limit: strategy.maxEvents,
                            orderBy: ['-timestamp'],
                            after: strategy.timeWindow,
                        }

                        const response = await api.events.list(params, strategy.maxEvents, teamId)

                        // Note: Can't store strategy here since cache isn't available in loader context
                        // The polling interval will use the fallback in afterMount

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
                    // TEMPORARY: Return empty result to avoid all GitHub API calls
                    // Go SDK will use async per-SDK fetching instead
                    console.info('[SDK Doctor] Skipping bulk GitHub API fetch - using per-SDK approach for Go only')

                    const result: Record<
                        SdkType,
                        { latestVersion: string; versions: string[]; releaseDates?: Record<string, string> }
                    > = {} as Record<
                        SdkType,
                        { latestVersion: string; versions: string[]; releaseDates?: Record<string, string> }
                    >

                    // Skip all bulk fetching to avoid GitHub API rate limits
                    // Individual SDKs will be processed as needed via async per-SDK approach
                    return result
                },
            },
        ],

        // DISABLED: Recent events for initialization detection (demo purposes)
        recentInitEvents: [
            [] as EventType[],
            {
                loadRecentInitEvents: async () => {
                    // Disabled for demo - multi-init detection postponed for post-MVP
                    return [] as EventType[]
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

        // Stub for multi-init detection (disabled for post-MVP)
        multipleInitDetection: [
            { detected: false, detectedAt: '', affectedUrls: [], sessionCount: 0 } as MultipleInitDetection,
            {},
        ],

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
                    // Only look at recent events to avoid cross-contamination
                    const tenMinutesAgo = Date.now() - 10 * 60 * 1000
                    const limitedEvents = recentEvents.slice(0, 15)

                    // Filter out PostHog's internal UI events (URLs containing /project/1/)
                    // In dev mode, also filter out test@posthog.com email events (dev UI interactions)
                    const customerEvents = limitedEvents.filter(
                        (event) =>
                            !event.properties?.$current_url?.includes('/project/1') &&
                            !(isDemoMode() && event.properties?.email === 'test@posthog.com')
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
                        return state
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

                        console.info(`[SDK Doctor Debug] Session ${sessionId}: ${sortedEvents.length} events`)
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
                            console.info(`[SDK Doctor Debug] No flag events in session ${sessionId}`)
                            return
                        }

                        console.info(`[SDK Doctor Debug] Found ${flagEvents.length} flag events in session`)

                        // Detect bootstrap state for contextual thresholds
                        const hasBootstrap = sortedEvents.some(
                            (event) => event.properties?.$feature_flag_bootstrapped === true
                        )

                        // Detect proper init patterns (e.g., presence of specific ready events)
                        const hasProperInitPattern = sortedEvents.some(
                            (event) =>
                                event.event === '$pageview' ||
                                event.event === '$identify' ||
                                event.properties?.$device_type // Common indicators of proper initialization
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
                        flagEvents.forEach((flagEvent, index) => {
                            const flagTime = new Date(flagEvent.timestamp).getTime()
                            const timeDiff = flagTime - firstEventTime

                            console.info(`[SDK Doctor Debug] Flag ${index + 1}: ${flagEvent.properties?.$feature_flag}`)
                            console.info(`[SDK Doctor Debug]   - Flag time: ${flagEvent.timestamp} (${flagTime})`)
                            console.info(`[SDK Doctor Debug]   - Time diff: ${timeDiff}ms`)
                            console.info(
                                `[SDK Doctor Debug]   - Bootstrapped: ${flagEvent.properties?.$feature_flag_bootstrapped}`
                            )

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
                            detectedAt: state.detectedAt || new Date().toISOString(),
                            flagsCalledBeforeLoading: Array.from(
                                new Set([...state.flagsCalledBeforeLoading, ...Array.from(problematicFlags)])
                            ),
                            exampleEventId: exampleEventId || state.exampleEventId,
                            exampleEventTimestamp: exampleEventTimestamp || state.exampleEventTimestamp,
                            flagExampleEvents: { ...state.flagExampleEvents, ...flagExampleEvents },
                            sessionCount: Math.max(uniqueSessions.size, state.sessionCount),
                        }
                    }

                    // Enhanced resolution detection: Check recent flag events for improved timing patterns
                    if (state.detected) {
                        const recentFlagEvents = webEvents
                            .filter((event) => event.event === '$feature_flag_called')
                            .slice(-5) // Last 5 flag events

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
                                        event.event === '$pageview' ||
                                        event.event === '$identify' ||
                                        event.properties?.$device_type
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
                                if (IS_DEBUG_MODE) {
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

                    // Use all events from our strategy-based fetch (up to strategy.maxEvents)
                    const limitedEvents = recentEvents.slice(0, 30) // Allow up to 30 events

                    // Filter out PostHog's internal UI events (URLs containing /project/1/) when in development
                    // Also filter out posthog-js-lite events as requested
                    // In dev mode, also filter out test@posthog.com email events (dev UI interactions)
                    const customerEvents = limitedEvents.filter(
                        (event) =>
                            !event.properties?.$current_url?.includes('/project/1') &&
                            event.properties?.$lib !== 'posthog-js-lite' &&
                            !(isDemoMode() && event.properties?.email === 'test@posthog.com')
                    )

                    const webEvents = customerEvents.filter((e) => e.properties?.$lib === 'web')

                    // Detect multiple SDK versions within the same session - a strong indicator of misconfiguration
                    // TODO: Implement multiple version detection logic
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

                    // Process all events to extract SDK versions
                    customerEvents.forEach((event) => {
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

        // Stub for multi-init SDKs (disabled for post-MVP)
        multipleInitSdks: [
            () => [],
            (): SdkVersionInfo[] => {
                // Always return empty array - multi-init detection disabled for post-MVP
                return []
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
        loadRecentEventsSuccess: async () => {
            // TODO: Multi-init detection temporarily disabled for post-MVP
            // await updateReleasesCache() - no longer needed

            // Fetch the latest versions to compare against for outdated version detection
            actions.loadLatestSdkVersions()
        },
        loadLatestSdkVersionsSuccess: async () => {
            // Handle async processing for all time-based detection SDKs
            const updatedMap = { ...values.sdkVersionsMap }
            const timeBasedSdks = [
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
            let hasTimeBasedSdks = false

            // Check if we have any time-based detection SDKs to process
            for (const [, info] of Object.entries(updatedMap)) {
                if (timeBasedSdks.includes(info.type)) {
                    hasTimeBasedSdks = true
                    break
                }
            }

            if (hasTimeBasedSdks) {
                // Process time-based detection SDKs asynchronously
                for (const [key, info] of Object.entries(updatedMap)) {
                    if (timeBasedSdks.includes(info.type)) {
                        try {
                            // DIRECT IMPLEMENTATION FOR GO SDK - bypass the complex pipeline
                            if (info.type === 'go') {
                                console.info(`[SDK Doctor] Direct Go SDK processing for version ${info.version}`)

                                // Get SDK data directly
                                const sdkData = await fetchSdkData('go')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] Go SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'desktop',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                const releaseDates = sdkData.releaseDates || {}

                                console.info(
                                    `[SDK Doctor] Go SDK direct check - Latest: ${latestVersion}, Current: ${info.version}`
                                )
                                console.info(`[SDK Doctor] Go SDK release dates available:`, Object.keys(releaseDates))

                                // Find the index of the current version
                                const currentIndex = versions.indexOf(info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Get release date for the current version
                                let releaseDate: string | undefined
                                let daysSinceRelease: number | undefined
                                let isRecentRelease = false

                                if (releaseDates[info.version]) {
                                    releaseDate = releaseDates[info.version]
                                    const releaseTimestamp = new Date(releaseDate).getTime()
                                    const now = Date.now()
                                    daysSinceRelease = Math.floor((now - releaseTimestamp) / (1000 * 60 * 60 * 24))
                                    isRecentRelease = daysSinceRelease < 2 // 48 hours
                                    console.info(
                                        `[SDK Doctor] Go SDK ${info.version} released on ${releaseDate}, ${daysSinceRelease} days ago, recent: ${isRecentRelease}`
                                    )
                                }

                                // Apply Go SDK specific logic (no time-based detection due to infrequent releases)
                                let isOutdated = false
                                if (info.version !== latestVersion) {
                                    if (releasesBehind >= 3) {
                                        // 3 or more releases behind - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Go SDK ${info.version} is ${releasesBehind} releases behind - marking as outdated`
                                        )
                                    } else {
                                        // 1-2 releases behind - close enough (Go SDK exception due to infrequent releases)
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Go SDK ${info.version} is ${releasesBehind} releases behind - marking as close enough (Go SDK exception)`
                                        )
                                    }
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated: false, // Not used for Go SDK
                                    deviceContext: 'desktop',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] Go SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'web') {
                                // DIRECT IMPLEMENTATION FOR WEB SDK - bypass the complex pipeline
                                console.info(`[SDK Doctor] Direct Web SDK processing for version ${info.version}`)

                                // Get SDK data directly
                                const sdkData = await fetchSdkData('web')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] Web SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'desktop',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                const releaseDates = sdkData.releaseDates || {}

                                console.info(
                                    `[SDK Doctor] Web SDK direct check - Latest: ${latestVersion}, Current: ${info.version}`
                                )
                                console.info(`[SDK Doctor] Web SDK release dates available:`, Object.keys(releaseDates))

                                // Find the index of the current version
                                const currentIndex = versions.indexOf(info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Get release date for the current version
                                let releaseDate: string | undefined
                                let daysSinceRelease: number | undefined
                                let isRecentRelease = false

                                if (releaseDates[info.version]) {
                                    releaseDate = releaseDates[info.version]
                                    const releaseTimestamp = new Date(releaseDate).getTime()
                                    const now = Date.now()
                                    daysSinceRelease = Math.floor((now - releaseTimestamp) / (1000 * 60 * 60 * 24))
                                    isRecentRelease = daysSinceRelease < 2 // 48 hours

                                    console.info(
                                        `[SDK Doctor] Web SDK ${info.version} released on ${releaseDate}, ${daysSinceRelease} days ago, recent: ${isRecentRelease}`
                                    )
                                }

                                // Apply the dual-check logic directly
                                let isOutdated = false
                                if (info.version !== latestVersion) {
                                    if (isRecentRelease) {
                                        // Recent release (within time threshold) - always "Close enough" regardless of releases behind
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Web SDK ${info.version} is ${releasesBehind} releases behind but recent (${daysSinceRelease} days old) - marking as close enough`
                                        )
                                    } else if (releasesBehind >= 3) {
                                        // 3 or more releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Web SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else if (releasesBehind >= 2) {
                                        // 2+ releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Web SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else {
                                        // 1 release behind - close enough
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Web SDK ${info.version} is ${releasesBehind} releases behind - marking as close enough`
                                        )
                                    }
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated: false, // Not used for direct implementation
                                    deviceContext: 'desktop',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] Web SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'python') {
                                // DIRECT IMPLEMENTATION FOR PYTHON SDK - bypass the complex pipeline
                                console.info(`[SDK Doctor] Direct Python SDK processing for version ${info.version}`)

                                // Get SDK data directly
                                const sdkData = await fetchSdkData('python')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] Python SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'desktop',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                const releaseDates = sdkData.releaseDates || {}

                                console.info(
                                    `[SDK Doctor] Python SDK direct check - Latest: ${latestVersion}, Current: ${info.version}`
                                )
                                console.info(
                                    `[SDK Doctor] Python SDK release dates available:`,
                                    Object.keys(releaseDates)
                                )

                                // Find the index of the current version
                                const currentIndex = versions.indexOf(info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Get release date for the current version
                                let releaseDate: string | undefined
                                let daysSinceRelease: number | undefined
                                let isRecentRelease = false

                                if (releaseDates[info.version]) {
                                    releaseDate = releaseDates[info.version]
                                    const releaseTimestamp = new Date(releaseDate).getTime()
                                    const now = Date.now()
                                    daysSinceRelease = Math.floor((now - releaseTimestamp) / (1000 * 60 * 60 * 24))
                                    isRecentRelease = daysSinceRelease < 2 // 48 hours

                                    console.info(
                                        `[SDK Doctor] Python SDK ${info.version} released on ${releaseDate}, ${daysSinceRelease} days ago, recent: ${isRecentRelease}`
                                    )
                                }

                                // Apply the dual-check logic directly
                                let isOutdated = false
                                if (info.version !== latestVersion) {
                                    if (isRecentRelease) {
                                        // Recent release (within time threshold) - always "Close enough" regardless of releases behind
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Python SDK ${info.version} is ${releasesBehind} releases behind but recent (${daysSinceRelease} days old) - marking as close enough`
                                        )
                                    } else if (releasesBehind >= 3) {
                                        // 3 or more releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Python SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else if (releasesBehind >= 2) {
                                        // 2+ releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Python SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else {
                                        // 1 release behind - close enough
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Python SDK ${info.version} is ${releasesBehind} releases behind - marking as close enough`
                                        )
                                    }
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated: false, // Not used for direct implementation
                                    deviceContext: 'desktop',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] Python SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'react-native') {
                                // DIRECT IMPLEMENTATION FOR REACT NATIVE SDK - bypass the complex pipeline
                                console.info(
                                    `[SDK Doctor] Direct React Native SDK processing for version ${info.version}`
                                )

                                // Get SDK data directly
                                const sdkData = await fetchSdkData('react-native')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] React Native SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'mobile',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                const releaseDates = sdkData.releaseDates || {}

                                console.info(
                                    `[SDK Doctor] React Native SDK direct check - Latest: ${latestVersion}, Current: ${info.version}`
                                )
                                console.info(
                                    `[SDK Doctor] React Native SDK release dates available:`,
                                    Object.keys(releaseDates)
                                )

                                // Find the index of the current version
                                const currentIndex = versions.indexOf(info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Get release date for the current version
                                let releaseDate: string | undefined
                                let daysSinceRelease: number | undefined
                                let isRecentRelease = false

                                if (releaseDates[info.version]) {
                                    releaseDate = releaseDates[info.version]
                                    const releaseTimestamp = new Date(releaseDate).getTime()
                                    const now = Date.now()
                                    daysSinceRelease = Math.floor((now - releaseTimestamp) / (1000 * 60 * 60 * 24))
                                    isRecentRelease = daysSinceRelease < 2 // 48 hours

                                    console.info(
                                        `[SDK Doctor] React Native SDK ${info.version} released on ${releaseDate}, ${daysSinceRelease} days ago, recent: ${isRecentRelease}`
                                    )
                                }

                                // Apply the dual-check logic directly
                                let isOutdated = false
                                if (info.version !== latestVersion) {
                                    if (isRecentRelease) {
                                        // Recent release (within time threshold) - always "Close enough" regardless of releases behind
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] React Native SDK ${info.version} is ${releasesBehind} releases behind but recent (${daysSinceRelease} days old) - marking as close enough`
                                        )
                                    } else if (releasesBehind >= 3) {
                                        // 3 or more releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] React Native SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else if (releasesBehind >= 2) {
                                        // 2+ releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] React Native SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else {
                                        // 1 release behind - close enough
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] React Native SDK ${info.version} is ${releasesBehind} releases behind - marking as close enough`
                                        )
                                    }
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated: false, // Not used for direct implementation
                                    deviceContext: 'mobile',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] React Native SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'flutter') {
                                // DIRECT IMPLEMENTATION FOR FLUTTER SDK - bypass the complex pipeline
                                console.info(`[SDK Doctor] Direct Flutter SDK processing for version ${info.version}`)

                                // Get SDK data directly
                                const sdkData = await fetchSdkData('flutter')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] Flutter SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'mobile',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                const releaseDates = sdkData.releaseDates || {}

                                console.info(
                                    `[SDK Doctor] Flutter SDK direct check - Latest: ${latestVersion}, Current: ${info.version}`
                                )
                                console.info(
                                    `[SDK Doctor] Flutter SDK release dates available:`,
                                    Object.keys(releaseDates)
                                )

                                // Find the index of the current version
                                const currentIndex = versions.indexOf(info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Get release date for the current version
                                let releaseDate: string | undefined
                                let daysSinceRelease: number | undefined
                                let isRecentRelease = false

                                if (releaseDates[info.version]) {
                                    releaseDate = releaseDates[info.version]
                                    const releaseTimestamp = new Date(releaseDate).getTime()
                                    const now = Date.now()
                                    daysSinceRelease = Math.floor((now - releaseTimestamp) / (1000 * 60 * 60 * 24))
                                    isRecentRelease = daysSinceRelease < 2 // 48 hours

                                    console.info(
                                        `[SDK Doctor] Flutter SDK ${info.version} released on ${releaseDate}, ${daysSinceRelease} days ago, recent: ${isRecentRelease}`
                                    )
                                }

                                // Apply the dual-check logic directly
                                let isOutdated = false
                                if (info.version !== latestVersion) {
                                    if (isRecentRelease) {
                                        // Recent release (within time threshold) - always "Close enough" regardless of releases behind
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Flutter SDK ${info.version} is ${releasesBehind} releases behind but recent (${daysSinceRelease} days old) - marking as close enough`
                                        )
                                    } else if (releasesBehind >= 3) {
                                        // 3 or more releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Flutter SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else if (releasesBehind >= 2) {
                                        // 2+ releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Flutter SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else {
                                        // 1 release behind - close enough
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Flutter SDK ${info.version} is ${releasesBehind} releases behind - marking as close enough`
                                        )
                                    }
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated: false, // Not used for direct implementation
                                    deviceContext: 'mobile',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] Flutter SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'ios') {
                                // DIRECT IMPLEMENTATION FOR iOS SDK - bypass the complex pipeline
                                console.info(`[SDK Doctor] Direct iOS SDK processing for version ${info.version}`)

                                // Get SDK data directly
                                const sdkData = await fetchSdkData('ios')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] iOS SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'mobile',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                const releaseDates = sdkData.releaseDates || {}

                                console.info(
                                    `[SDK Doctor] iOS SDK direct check - Latest: ${latestVersion}, Current: ${info.version}`
                                )
                                console.info(`[SDK Doctor] iOS SDK release dates available:`, Object.keys(releaseDates))

                                // Find the index of the current version
                                const currentIndex = versions.indexOf(info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Get release date for the current version
                                let releaseDate: string | undefined
                                let daysSinceRelease: number | undefined
                                let isRecentRelease = false

                                if (releaseDates[info.version]) {
                                    releaseDate = releaseDates[info.version]
                                    const releaseTimestamp = new Date(releaseDate).getTime()
                                    const now = Date.now()
                                    daysSinceRelease = Math.floor((now - releaseTimestamp) / (1000 * 60 * 60 * 24))
                                    isRecentRelease = daysSinceRelease < 2 // 48 hours

                                    console.info(
                                        `[SDK Doctor] iOS SDK ${info.version} released on ${releaseDate}, ${daysSinceRelease} days ago, recent: ${isRecentRelease}`
                                    )
                                }

                                // Apply the dual-check logic directly
                                let isOutdated = false
                                if (info.version !== latestVersion) {
                                    if (isRecentRelease) {
                                        // Recent release (within time threshold) - always "Close enough" regardless of releases behind
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] iOS SDK ${info.version} is ${releasesBehind} releases behind but recent (${daysSinceRelease} days old) - marking as close enough`
                                        )
                                    } else if (releasesBehind >= 3) {
                                        // 3 or more releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] iOS SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else if (releasesBehind >= 2) {
                                        // 2+ releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] iOS SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else {
                                        // 1 release behind - close enough
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] iOS SDK ${info.version} is ${releasesBehind} releases behind - marking as close enough`
                                        )
                                    }
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated: false, // Not used for direct implementation
                                    deviceContext: 'mobile',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] iOS SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'android') {
                                // DIRECT IMPLEMENTATION FOR ANDROID SDK - bypass the complex pipeline
                                console.info(`[SDK Doctor] Direct Android SDK processing for version ${info.version}`)

                                // Get SDK data directly
                                const sdkData = await fetchSdkData('android')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] Android SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'mobile',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                const releaseDates = sdkData.releaseDates || {}

                                console.info(
                                    `[SDK Doctor] Android SDK direct check - Latest: ${latestVersion}, Current: ${info.version}`
                                )
                                console.info(
                                    `[SDK Doctor] Android SDK release dates available:`,
                                    Object.keys(releaseDates)
                                )

                                // Find the index of the current version
                                const currentIndex = versions.indexOf(info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Get release date for the current version
                                let releaseDate: string | undefined
                                let daysSinceRelease: number | undefined
                                let isRecentRelease = false

                                if (releaseDates[info.version]) {
                                    releaseDate = releaseDates[info.version]
                                    const releaseTimestamp = new Date(releaseDate).getTime()
                                    const now = Date.now()
                                    daysSinceRelease = Math.floor((now - releaseTimestamp) / (1000 * 60 * 60 * 24))
                                    isRecentRelease = daysSinceRelease < 2 // 48 hours

                                    console.info(
                                        `[SDK Doctor] Android SDK ${info.version} released on ${releaseDate}, ${daysSinceRelease} days ago, recent: ${isRecentRelease}`
                                    )
                                }

                                // Apply the dual-check logic directly
                                let isOutdated = false
                                if (info.version !== latestVersion) {
                                    if (isRecentRelease) {
                                        // Recent release (within time threshold) - always "Close enough" regardless of releases behind
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Android SDK ${info.version} is ${releasesBehind} releases behind but recent (${daysSinceRelease} days old) - marking as close enough`
                                        )
                                    } else if (releasesBehind >= 3) {
                                        // 3 or more releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Android SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else if (releasesBehind >= 2) {
                                        // 2+ releases behind AND not recent - outdated
                                        isOutdated = true
                                        console.info(
                                            `[SDK Doctor] Android SDK ${info.version} is ${releasesBehind} releases behind and ${daysSinceRelease} days old - marking as outdated`
                                        )
                                    } else {
                                        // 1 release behind - close enough
                                        isOutdated = false
                                        console.info(
                                            `[SDK Doctor] Android SDK ${info.version} is ${releasesBehind} releases behind - marking as close enough`
                                        )
                                    }
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated: false, // Not used for direct implementation
                                    deviceContext: 'mobile',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] Android SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'php') {
                                // DIRECT IMPLEMENTATION FOR PHP SDK - simplified logic
                                console.info(`[SDK Doctor] Direct PHP SDK processing for version ${info.version}`)

                                // Get PHP SDK data directly
                                const sdkData = await fetchSdkData('php')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] PHP SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'desktop',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions

                                // Calculate releases behind
                                const currentIndex = versions.findIndex((v) => v === info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Simplified logic: 0 = current, 1-2 = close enough, 3+ = outdated
                                let isOutdated = false
                                if (releasesBehind >= 3) {
                                    isOutdated = true
                                    console.info(
                                        `[SDK Doctor] PHP SDK ${info.version} is ${releasesBehind} releases behind - marking as outdated`
                                    )
                                } else {
                                    console.info(
                                        `[SDK Doctor] PHP SDK ${info.version} is ${releasesBehind} releases behind - marking as ${releasesBehind === 0 ? 'current' : 'close enough'}`
                                    )
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate: undefined,
                                    daysSinceRelease: undefined,
                                    isAgeOutdated: false,
                                    deviceContext: 'desktop',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] PHP SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'ruby') {
                                // DIRECT IMPLEMENTATION FOR RUBY SDK - simplified logic
                                console.info(`[SDK Doctor] Direct Ruby SDK processing for version ${info.version}`)

                                // Get Ruby SDK data directly
                                const sdkData = await fetchSdkData('ruby')

                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] Ruby SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'desktop',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }

                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions

                                // Calculate releases behind
                                const currentIndex = versions.findIndex((v) => v === info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex

                                // Simplified logic: 0 = current, 1-2 = close enough, 3+ = outdated
                                let isOutdated = false
                                if (releasesBehind >= 3) {
                                    isOutdated = true
                                    console.info(
                                        `[SDK Doctor] Ruby SDK ${info.version} is ${releasesBehind} releases behind - marking as outdated`
                                    )
                                } else {
                                    console.info(
                                        `[SDK Doctor] Ruby SDK ${info.version} is ${releasesBehind} releases behind - marking as ${releasesBehind === 0 ? 'current' : 'close enough'}`
                                    )
                                }

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate: undefined,
                                    daysSinceRelease: undefined,
                                    isAgeOutdated: false,
                                    deviceContext: 'desktop',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }

                                console.info(
                                    `[SDK Doctor] Ruby SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'elixir') {
                                // DIRECT IMPLEMENTATION FOR ELIXIR SDK - simplified logic
                                console.info(`[SDK Doctor] Direct Elixir SDK processing for version ${info.version}`)
                                // Get Elixir SDK data directly
                                const sdkData = await fetchSdkData('elixir')
                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] Elixir SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'desktop',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }
                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                // Calculate releases behind
                                const currentIndex = versions.findIndex((v) => v === info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex
                                // Simplified logic: 0 = current, 1-2 = close enough, 3+ = outdated
                                let isOutdated = false
                                if (releasesBehind >= 3) {
                                    isOutdated = true
                                    console.info(
                                        `[SDK Doctor] Elixir SDK ${info.version} is ${releasesBehind} releases behind - marking as outdated`
                                    )
                                } else {
                                    console.info(
                                        `[SDK Doctor] Elixir SDK ${info.version} is ${releasesBehind} releases behind - marking as ${releasesBehind === 0 ? 'current' : 'close enough'}`
                                    )
                                }
                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate: undefined,
                                    daysSinceRelease: undefined,
                                    isAgeOutdated: false,
                                    deviceContext: 'desktop',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }
                                console.info(
                                    `[SDK Doctor] Elixir SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else if (info.type === 'dotnet') {
                                // DIRECT IMPLEMENTATION FOR .NET SDK - simplified logic
                                console.info(`[SDK Doctor] Direct .NET SDK processing for version ${info.version}`)
                                // Get .NET SDK data directly
                                const sdkData = await fetchSdkData('dotnet')
                                if (!sdkData || !sdkData.versions || sdkData.versions.length === 0) {
                                    console.warn('[SDK Doctor] .NET SDK: No version data available')
                                    updatedMap[key] = {
                                        ...info,
                                        isOutdated: false,
                                        releasesAhead: 0,
                                        latestVersion: undefined,
                                        releaseDate: undefined,
                                        daysSinceRelease: undefined,
                                        isAgeOutdated: false,
                                        deviceContext: 'desktop',
                                        eventVolume: categorizeEventVolume(info.count),
                                        lastSeenTimestamp: new Date().toISOString(),
                                        error: 'The Doctor is unavailable. Please try again later.',
                                    }
                                    continue
                                }
                                const latestVersion = sdkData.versions[0]
                                const versions = sdkData.versions
                                // Calculate releases behind
                                const currentIndex = versions.findIndex((v) => v === info.version)
                                const releasesBehind = currentIndex === -1 ? versions.length : currentIndex
                                // Simplified logic: 0 = current, 1-2 = close enough, 3+ = outdated
                                let isOutdated = false
                                if (releasesBehind >= 3) {
                                    isOutdated = true
                                    console.info(
                                        `[SDK Doctor] .NET SDK ${info.version} is ${releasesBehind} releases behind - marking as outdated`
                                    )
                                } else {
                                    console.info(
                                        `[SDK Doctor] .NET SDK ${info.version} is ${releasesBehind} releases behind - marking as ${releasesBehind === 0 ? 'current' : 'close enough'}`
                                    )
                                }
                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead: releasesBehind,
                                    latestVersion,
                                    releaseDate: undefined,
                                    daysSinceRelease: undefined,
                                    isAgeOutdated: false,
                                    deviceContext: 'desktop',
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error: undefined,
                                }
                                console.info(
                                    `[SDK Doctor] .NET SDK ${info.version} final status - Outdated: ${isOutdated}, Releases behind: ${releasesBehind}`
                                )
                            } else {
                                // Use the existing async check for remaining SDKs
                                console.info(
                                    `[SDK Doctor] Using async check for ${info.type} SDK version ${info.version}`
                                )
                                const versionCheckResult = await checkVersionAgainstLatestAsync(info.type, info.version)
                                const {
                                    isOutdated,
                                    releasesAhead,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated,
                                    error,
                                } = versionCheckResult

                                const deviceContext =
                                    'deviceContext' in versionCheckResult && versionCheckResult.deviceContext
                                        ? (versionCheckResult.deviceContext as 'mobile' | 'desktop' | 'mixed')
                                        : determineDeviceContext(info.type)

                                updatedMap[key] = {
                                    ...info,
                                    isOutdated,
                                    releasesAhead,
                                    latestVersion,
                                    releaseDate,
                                    daysSinceRelease,
                                    isAgeOutdated,
                                    deviceContext,
                                    eventVolume: categorizeEventVolume(info.count),
                                    lastSeenTimestamp: new Date().toISOString(),
                                    error,
                                }
                            }
                        } catch (error) {
                            console.warn(`[SDK Doctor] Error processing ${info.type} SDK ${info.version}:`, error)
                        }
                    }
                }

                // Update the state with the processed SDK data
                actions.updateSdkVersionsMap(updatedMap)
            }
        },
    })),

    afterMount(({ actions, cache }) => {
        // Load recent events when the logic is mounted
        actions.loadRecentEvents()

        // NEW: Strategy-based adaptive polling
        const updatePollingInterval = (): void => {
            if (cache.pollingInterval) {
                window.clearInterval(cache.pollingInterval)
            }

            // Use interval from current strategy, with fallback
            const intervalMs = cache.currentStrategy?.intervalMs || 5000

            cache.pollingInterval = window.setInterval(() => {
                actions.loadRecentEvents()
            }, intervalMs)
        }

        // Initial setup
        updatePollingInterval()

        // Update interval after each event load (when strategy might change)
        cache.intervalUpdater = window.setInterval(updatePollingInterval, 60000) // Check every minute
    }),

    beforeUnmount(({ cache }) => {
        // Clean up the intervals when unmounting
        if (cache.pollingInterval) {
            window.clearInterval(cache.pollingInterval)
            cache.pollingInterval = null
        }
        if (cache.intervalUpdater) {
            window.clearInterval(cache.intervalUpdater)
            cache.intervalUpdater = null
        }
    }),
])

// NEW: Age-based detection utilities
const DEVICE_CONTEXT_CONFIG: DeviceContextConfig = {
    mobileSDKs: ['ios', 'android', 'flutter', 'react-native'],
    desktopSDKs: ['web', 'node', 'python', 'php', 'ruby', 'go', 'dotnet', 'elixir'],
    volumeThresholds: { low: 10, medium: 50, high: Infinity },
    ageThresholds: { warnAfterWeeks: 8, criticalAfterWeeks: 16 },
}

function calculateVersionAge(releaseDate: string): number {
    const release = new Date(releaseDate)
    const now = new Date()
    return Math.floor((now.getTime() - release.getTime()) / (1000 * 60 * 60 * 24))
}

function determineDeviceContext(sdkType: SdkType): 'mobile' | 'desktop' | 'mixed' {
    if (DEVICE_CONTEXT_CONFIG.mobileSDKs.includes(sdkType)) {
        return 'mobile'
    }
    if (DEVICE_CONTEXT_CONFIG.desktopSDKs.includes(sdkType)) {
        return 'desktop'
    }
    return 'mixed'
}

function categorizeEventVolume(count: number): 'low' | 'medium' | 'high' {
    if (count < DEVICE_CONTEXT_CONFIG.volumeThresholds.low) {
        return 'low'
    }
    if (count < DEVICE_CONTEXT_CONFIG.volumeThresholds.medium) {
        return 'medium'
    }
    return 'high'
}

// NEW: Customer volume estimation and sampling strategy
interface SamplingStrategy {
    timeWindow: string // e.g., '-24h', '-7d'
    maxEvents: number
    minEventsForAnalysis: number
    contextBalancing: boolean
    intervalMs: number // Polling frequency
}

function isDemoMode(): boolean {
    const url = window.location.href
    return (
        url.includes('localhost') ||
        url.includes('127.0.0.1') ||
        url.includes('demo') ||
        url.includes(':8000') ||
        url.includes(':8010')
    ) // PostHog dev server
}

function determineSamplingStrategy(estimatedEventsPerMinute: number): SamplingStrategy {
    // Demo mode override for testing
    if (isDemoMode()) {
        return {
            timeWindow: '-1h', // Short window for fast testing
            maxEvents: 20, // Reasonable sample size
            minEventsForAnalysis: 3,
            contextBalancing: false, // Simple for demos
            intervalMs: 3000, // 3 seconds - responsive for demos
        }
    }
    if (estimatedEventsPerMinute > 1000) {
        // High-volume customers
        return {
            timeWindow: '-6h', // Shorter window, recent data
            maxEvents: 100, // Larger sample
            minEventsForAnalysis: 20,
            contextBalancing: true, // Ensure both mobile/desktop representation
            intervalMs: 10000, // 10 seconds - less frequent for high volume
        }
    } else if (estimatedEventsPerMinute > 50) {
        // Medium-volume customers
        return {
            timeWindow: '-24h',
            maxEvents: 50,
            minEventsForAnalysis: 10,
            contextBalancing: true,
            intervalMs: 5000, // 5 seconds - standard
        }
    }
    // Low-volume customers
    return {
        timeWindow: '-7d', // Longer window to get sufficient data
        maxEvents: 30,
        minEventsForAnalysis: 5,
        contextBalancing: false, // Take what we can get
        intervalMs: 2000, // 2 seconds - more responsive for low volume
    }
}

// NEW: Async version comparison function with on-demand SDK data fetching
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
    console.info(`[SDK Doctor] checkVersionAgainstLatestAsync called for ${type} version ${version}`)
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
            console.info(
                `[SDK Doctor] checkVersionAgainstLatestAsync - Go releaseDates preserved:`,
                latestVersionsData[type]?.releaseDates
                    ? Object.keys(latestVersionsData[type].releaseDates!).slice(0, 3)
                    : 'undefined'
            )
        }

        return checkVersionAgainstLatest(type, version, latestVersionsData)
    } catch (error) {
        console.warn(`[SDK Doctor] Error in async version check for ${type}:`, error)
        return {
            isOutdated: false,
            releasesAhead: 0,
            error: 'Failed to fetch version data',
        }
    }
}

// Enhanced version comparison function using semver utilities
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
        const releaseCountOutdated = releasesBehind > 2

        if (IS_DEBUG_MODE) {
            console.info(
                `[SDK Doctor] Release count check: releasesBehind=${releasesBehind}, releaseCountOutdated=${releaseCountOutdated}`
            )
            console.info(
                `[SDK Doctor] String comparison: "${version}" === "${latestVersion}" = ${version === latestVersion}`
            )
        }

        // Age-based analysis
        const deviceContext = determineDeviceContext(type)
        const releaseDates = latestVersionsData[type]?.releaseDates
        const releaseDate = releaseDates?.[version]

        // Debug logging for Go SDK
        if (type === 'go') {
            console.info(`[SDK Doctor] Go version lookup: checking version "${version}" in releaseDates`)
            console.info(`[SDK Doctor] Go releaseDates keys:`, releaseDates ? Object.keys(releaseDates) : 'undefined')
            console.info(`[SDK Doctor] Go releaseDate found:`, releaseDate || 'NOT FOUND')
        }

        let daysSinceRelease: number | undefined
        let isAgeOutdated = false

        if (releaseDate) {
            daysSinceRelease = calculateVersionAge(releaseDate)
            const weeksOld = daysSinceRelease / 7

            // Age-based outdated detection: >8 weeks old AND newer releases exist
            isAgeOutdated = weeksOld > DEVICE_CONTEXT_CONFIG.ageThresholds.warnAfterWeeks && releasesBehind > 0
        }

        // Dual check logic: Don't flag as "Outdated" if version released <48 hours ago, even if 2+ releases behind
        let isRecentRelease = false

        // Debug logging for Flutter specifically

        if (daysSinceRelease !== undefined) {
            isRecentRelease = daysSinceRelease < 2 // 48 hours
        } else if (
            ['web', 'python', 'node', 'react-native', 'flutter', 'ios', 'android', 'go', 'ruby'].includes(type)
        ) {
            // For these SDKs, we require GitHub API data for accurate detection
            // Return error state instead of misleading fallbacks
            const errorMessage = `The Doctor is unavailable. Please try again later.`
            console.error(`[SDK Doctor] ${errorMessage} (Missing GitHub release date data for version ${version})`)

            return {
                isOutdated: false,
                error: errorMessage,
                releasesAhead: 0,
                latestVersion,
                releaseDate,
                daysSinceRelease,
                isAgeOutdated: false,
                deviceContext,
            }
        } else {
            console.info(`[SDK Doctor] No time-based detection available for SDK type: ${type}`)
        }

        // Apply SDK-specific logic
        let isOutdated = false
        if (['go', 'php', 'ruby', 'elixir', 'dotnet'].includes(type)) {
            // Go, PHP, Ruby, Elixir, .NET SDK exception: infrequent releases, so 1-2 releases = "Close enough", 3+ = "Outdated"
            isOutdated = releasesBehind >= 3
            const statusLabel = releasesBehind === 0 ? 'current' : releasesBehind < 3 ? 'close enough' : 'outdated'
            console.info(
                `[SDK Doctor] ${type} SDK ${version} is ${releasesBehind} releases behind - marking as ${statusLabel} (${type} SDK exception)`
            )
        } else {
            // Standard logic: 2+ releases behind AND >48h old
            // This means even 3+ releases behind shows "Close enough" if released recently
            isOutdated = releasesBehind >= 2 && !isRecentRelease
        }

        if (IS_DEBUG_MODE) {
            console.info(
                `[SDK Doctor] Time-based detection: daysSinceRelease=${daysSinceRelease}, isRecentRelease=${isRecentRelease}`
            )
            console.info(
                `[SDK Doctor] Final result: isOutdated=${isOutdated} (releasesBehind=${releasesBehind}, isAgeOutdated=${isAgeOutdated})`
            )
        }

        return {
            isOutdated: isOutdated || isAgeOutdated, // Combine dual-check and age-based
            releasesAhead: Math.max(0, releasesBehind),
            latestVersion,
            releaseDate,
            daysSinceRelease,
            isAgeOutdated,
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
