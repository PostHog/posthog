/* oxlint-disable no-console */
import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { isNotNil } from 'lib/utils'
import { getAppContext } from 'lib/utils/getAppContext'
import { diffVersions, parseVersion, tryParseVersion } from 'lib/utils/semver'
import { teamLogic } from 'scenes/teamLogic'

import { EventsListQueryParams, EventType } from '~/types'

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

                    // Check cache first (but with short expiry for debugging)
                    const cachedData = getGitHubCache()
                    if (cachedData && Date.now() - cachedData.timestamp < 5 * 60 * 1000) {
                        // 5 minute expiry for debugging
                        if (IS_DEBUG_MODE) {
                            console.info('[SDK Doctor] Using cached GitHub data (debug mode)')
                        }
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
                            dotnet: { repo: 'posthog-dotnet', versionPrefix: 'v' },
                            elixir: { repo: 'posthog-elixir' },
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

                                // Special handling for Web SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'web') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/browser/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Extract version numbers using the same regex as test files
                                            const versionMatches = changelogText.match(/^## (\d+\.\d+\.\d+)$/gm)

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) => match.replace(/^## /, ''))
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for React Native SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'react-native') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/react-native/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Extract version numbers using the same regex as test files
                                            const versionMatches = changelogText.match(/^## (\d+\.\d+\.\d+)$/gm)

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) => match.replace(/^## /, ''))
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for Node.js SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'node') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-js/main/packages/node/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Node.js CHANGELOG.md format: "## 5.6.0 – 2025-07-15"
                                            const versionMatches = changelogText.match(/^## (\d+\.\d+\.\d+) –/gm)

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) => match.replace(/^## /, '').replace(/ –.*$/, '')) // Remove "## " and " – date" parts
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for Python SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'python') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-python/master/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Python CHANGELOG.md format: "# 6.5.0 - 2025-08-08"
                                            const versionMatches = changelogText.match(
                                                /^# (\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$/gm
                                            )

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) =>
                                                        match.replace(/^# /, '').replace(/ - \d{4}-\d{2}-\d{2}$/, '')
                                                    ) // Remove "# " and " - YYYY-MM-DD" parts
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for Flutter SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'flutter') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-flutter/main/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Extract version numbers using the same regex as test files
                                            const versionMatches = changelogText.match(/^## (\d+\.\d+\.\d+)$/gm)

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) => match.replace(/^## /, ''))
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for iOS SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'ios') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-ios/main/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // iOS CHANGELOG.md format: "## 3.30.1 - 2025-08-12"
                                            const versionMatches = changelogText.match(
                                                /^## (\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$/gm
                                            )

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) =>
                                                        match.replace(/^## /, '').replace(/ - \d{4}-\d{2}-\d{2}$/, '')
                                                    ) // Remove "## " and " - YYYY-MM-DD" parts
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for Android SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'android') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-android/main/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Android CHANGELOG.md format: "## 3.20.2 - 2025-08-07"
                                            const versionMatches = changelogText.match(
                                                /^## (\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$/gm
                                            )

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) =>
                                                        match.replace(/^## /, '').replace(/ - \d{4}-\d{2}-\d{2}$/, '')
                                                    ) // Remove "## " and " - YYYY-MM-DD" parts
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for Go SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'go') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-go/master/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Go CHANGELOG.md format: "## 1.6.3"
                                            const versionMatches = changelogText.match(/^## (\d+\.\d+\.\d+)$/gm)

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) => match.replace(/^## /, '')) // Remove "## " prefix
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for Ruby SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'ruby') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-ruby/main/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Ruby CHANGELOG.md format: ## 3.1.2 (sometimes with dates like ## 3.1.0 - 2025-05-20)
                                            const versionMatches = changelogText.match(/^## (\d+\.\d+\.\d+)/gm)

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) => match.replace(/^## /, '').replace(/ [–-].*$/, '')) // Remove "## " and any date parts
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for Elixir SDK: use CHANGELOG.md instead of GitHub releases
                                if (sdkType === 'elixir') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-elixir/master/CHANGELOG.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch CHANGELOG.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // Elixir CHANGELOG.md format: ## 1.1.0 - 2025-07-01
                                            const versionMatches = changelogText.match(
                                                /^## (\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$/gm
                                            )

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) =>
                                                        match.replace(/^## /, '').replace(/ - \d{4}-\d{2}-\d{2}$/, '')
                                                    ) // Remove "## " and " - YYYY-MM-DD" parts
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from CHANGELOG.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // Special handling for PHP SDK: use History.md instead of GitHub releases
                                if (sdkType === 'php') {
                                    const changelogPromise = fetch(
                                        'https://raw.githubusercontent.com/PostHog/posthog-php/master/History.md'
                                    )
                                        .then((r) => {
                                            if (!r.ok) {
                                                throw new Error(`Failed to fetch History.md: ${r.status}`)
                                            }
                                            return r.text()
                                        })
                                        .then((changelogText) => {
                                            // PHP History.md format: "3.6.0 / 2025-04-30"
                                            const versionMatches = changelogText.match(
                                                /^(\d+\.\d+\.\d+) \/ \d{4}-\d{2}-\d{2}$/gm
                                            )

                                            if (versionMatches) {
                                                const versions = versionMatches
                                                    .map((match) => match.replace(/ \/ \d{4}-\d{2}-\d{2}$/, '')) // Remove " / YYYY-MM-DD" part
                                                    .filter((v) => /^\d+\.\d+\.\d+$/.test(v)) // Ensure valid semver format

                                                if (versions.length > 0) {
                                                    if (IS_DEBUG_MODE) {
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} versions found from History.md:`,
                                                            versions.slice(0, 5)
                                                        )
                                                        console.info(
                                                            `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                        )
                                                    }
                                                    return {
                                                        sdkType,
                                                        versions: versions,
                                                        latestVersion: versions[0],
                                                    }
                                                }
                                            }
                                            return null
                                        })

                                    return changelogPromise
                                }

                                // For other SDKs, use GitHub releases API
                                const cacheBuster = Date.now()
                                const tagsPromise = fetch(
                                    `https://api.github.com/repos/PostHog/${repo}/releases?_=${cacheBuster}`,
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
                                    .then((releases) => {
                                        if (releases && Array.isArray(releases) && releases.length > 0) {
                                            // Extract versions from releases
                                            const versions = releases
                                                .map((release: any) => {
                                                    const tagName = release.tag_name
                                                    if (!tagName) {
                                                        return null
                                                    }

                                                    // For Node.js SDK, only consider tags with the "node-" prefix
                                                    if (isNodeSdk) {
                                                        if (tagName.startsWith('node-')) {
                                                            // Remove the "node-" prefix for comparison
                                                            const nodeVersion = tagName.replace(/^node-/, '')
                                                            return tryParseVersion(nodeVersion) ? nodeVersion : null
                                                        }
                                                        return null
                                                    }

                                                    // Note: Web SDK now uses CHANGELOG.md approach (handled above)
                                                    // This section only handles non-web SDKs

                                                    // For other SDKs, use the original logic
                                                    const name = tagName.replace(/^v/, '')
                                                    return tryParseVersion(name) ? name : null
                                                })
                                                .filter(isNotNil)

                                            if (versions.length > 0) {
                                                if (IS_DEBUG_MODE) {
                                                    console.info(
                                                        `[SDK Doctor] ${sdkType} versions found:`,
                                                        versions.slice(0, 5)
                                                    )
                                                    console.info(
                                                        `[SDK Doctor] ${sdkType} latestVersion: "${versions[0]}"`
                                                    )
                                                }
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
                        if (IS_DEBUG_MODE) {
                            console.info(
                                '[SDK Doctor] Final result summary:',
                                Object.keys(result).map((key) => `${key}: ${result[key as SdkType]?.latestVersion}`)
                            )
                        }
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
                    const customerEvents = limitedEvents.filter(
                        (event) => !event.properties?.$current_url?.includes('/project/1/')
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

                    // Ensure we only look at the most recent 15 events maximum
                    const limitedEvents = recentEvents.slice(0, 15)

                    // Filter out PostHog's internal UI events (URLs containing /project/1/) when in development
                    // Also filter out posthog-js-lite events as requested
                    const customerEvents = limitedEvents.filter(
                        (event) =>
                            !event.properties?.$current_url?.includes('/project/1/') &&
                            event.properties?.$lib !== 'posthog-js-lite'
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
                            if (info.type === 'dotnet') {
                                libName = 'posthog-dotnet'
                            }
                            if (info.type === 'elixir') {
                                libName = 'posthog-elixir'
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

    listeners(({ actions }) => ({
        loadRecentEventsSuccess: async () => {
            // TODO: Multi-init detection temporarily disabled for post-MVP
            // await updateReleasesCache() - no longer needed

            // Fetch the latest versions to compare against for outdated version detection
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
    } else if (lib === 'posthog-dotnet') {
        return major < 1
    } else if (lib === 'posthog-elixir') {
        return major < 1
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
    if (IS_DEBUG_MODE) {
        console.info(`[SDK Doctor] checkVersionAgainstLatest for ${type} version ${version}`)
        console.info(`[SDK Doctor] Available data:`, Object.keys(latestVersionsData))
    }

    // Log web SDK data specifically for debugging
    if (IS_DEBUG_MODE) {
        if (type === 'web' && latestVersionsData.web) {
            console.info(`[SDK Doctor] Web SDK latestVersion: "${latestVersionsData.web.latestVersion}"`)
            console.info(`[SDK Doctor] Web SDK first 5 versions:`, latestVersionsData.web.versions.slice(0, 5))
        }

        // Log Node.js SDK data specifically for debugging
        if (type === 'node' && latestVersionsData.node) {
            console.info(`[SDK Doctor] Node.js SDK latestVersion: "${latestVersionsData.node.latestVersion}"`)
            console.info(`[SDK Doctor] Node.js SDK first 5 versions:`, latestVersionsData.node.versions.slice(0, 5))
        } else if (type === 'node') {
            console.warn(`[SDK Doctor] No Node.js SDK data available in latestVersionsData!`)
            console.info(`[SDK Doctor] Available types:`, Object.keys(latestVersionsData))
        }
    }

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
    if (type === 'dotnet') {
        lib = 'posthog-dotnet'
    }
    if (type === 'elixir') {
        lib = 'posthog-elixir'
    }

    // TODO: Node.js now uses CHANGELOG.md data - removed hardcoded version logic

    // If we don't have data for this SDK type or the SDK type is "other", fall back to hardcoded check
    if (!latestVersionsData[type] || type === 'other') {
        // console.log(`[SDK Doctor] Falling back to hardcoded check for ${type} (lib=${lib})`)
        const isOutdated = checkIfVersionOutdated(lib, version)
        // console.log(`[SDK Doctor] Hardcoded check result for ${lib} ${version}: isOutdated=${isOutdated}`)
        return { isOutdated }
    }

    const latestVersion = latestVersionsData[type].latestVersion
    const allVersions = latestVersionsData[type].versions

    if (IS_DEBUG_MODE) {
        console.info(`[SDK Doctor] Comparing ${version} against latest ${latestVersion}`)
        console.info(`[SDK Doctor] All versions available:`, allVersions)
    }

    try {
        // Parse versions for comparison
        const currentVersionParsed = parseVersion(version)
        const latestVersionParsed = parseVersion(latestVersion)

        // Check if versions differ
        const diff = diffVersions(latestVersionParsed, currentVersionParsed)

        // Count number of versions behind
        const versionIndex = allVersions.indexOf(version)
        let releasesBehind = versionIndex === -1 ? -1 : versionIndex

        if (IS_DEBUG_MODE) {
            console.info(`[SDK Doctor] Version ${version} is at index ${versionIndex} in versions array`)
            console.info(`[SDK Doctor] Releases behind: ${releasesBehind}`)
            console.info(`[SDK Doctor] Version diff:`, diff)
        }

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

        const isOutdated = releasesBehind >= 2
        if (IS_DEBUG_MODE) {
            console.info(
                `[SDK Doctor] Final result: isOutdated=${isOutdated}, releasesAhead=${releasesBehind}, latestVersion=${latestVersion}`
            )
        }
        if (IS_DEBUG_MODE) {
            console.info(
                `[SDK Doctor] String comparison: "${version}" === "${latestVersion}" = ${version === latestVersion}`
            )
        }

        // Consider outdated if 2+ versions behind (2 or more releases)
        return {
            isOutdated: isOutdated,
            releasesAhead: Math.max(0, releasesBehind),
            latestVersion,
        }
    } catch {
        // If we can't parse the versions, fall back to the hardcoded check
        // console.log(`[SDK Doctor] Error parsing versions, falling back to hardcoded check for ${lib}`)

        return {
            isOutdated: checkIfVersionOutdated(lib, version),
            latestVersion,
        }
    }
}
