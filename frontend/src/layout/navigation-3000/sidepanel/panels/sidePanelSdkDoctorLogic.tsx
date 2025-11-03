import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { diffVersions, parseVersion } from 'lib/utils/semver'

import type { sidePanelSdkDoctorLogicType } from './sidePanelSdkDoctorLogicType'

// Supported SDK types for version detection and health monitoring
export type SdkType =
    | 'web'
    | 'posthog-ios'
    | 'posthog-android'
    | 'posthog-node'
    | 'posthog-python'
    | 'posthog-php'
    | 'posthog-ruby'
    | 'posthog-go'
    | 'posthog-flutter'
    | 'posthog-react-native'
    | 'posthog-dotnet'
    | 'posthog-elixir'

// Small helper to define what our versions look like
export type SdkVersion = `${string}.${string}.${string}`

// For a given SDK, we want to know the latest version and the release dates of the more recent versions
export type SdkVersionInfo = {
    latestVersion: SdkVersion
    releaseDates: Record<SdkVersion, string>
}

// For a team we have a map of SDK types to all of the versions we say in recent times
// This is what we receive from the backend, we then do some calculations in the UI to determine
// what we should be displaying in the UI
export type TeamSdkVersionInfo = {
    lib_version: SdkVersion
    max_timestamp: string
    count: number
}

export type TeamSdkVersionsInfo = {
    [key in SdkType]?: TeamSdkVersionInfo[]
}

// This is the final data used to display in the UI
export type AugmentedTeamSdkVersionsInfo = {
    [key in SdkType]?: {
        isOutdated: boolean
        isOld: boolean
        needsUpdating: boolean
        currentVersion: SdkVersion
        allReleases: AugmentedTeamSdkVersionsInfoRelease[]
    }
}

export type AugmentedTeamSdkVersionsInfoRelease = {
    type: SdkType
    version: SdkVersion
    maxTimestamp: string
    count: number
    latestVersion: string
    releaseDate: string | undefined
    daysSinceRelease: number | undefined
    isOutdated: boolean
    isOld: boolean
    needsUpdating: boolean
}

/**
 * Overall health status for SDK version monitoring
 */
export type SdkHealthStatus = 'danger' | 'warning' | 'success'

/**
 * SDK Doctor - PostHog SDK Health Monitoring
 *
 * Detects installed SDKs and their versions across a team's events.
 * Provides smart version outdatedness detection.
 *
 * Architecture:
 * - Backend detection: Team SDK detections cached server-side (72h Redis, refreshed every 12 hours)
 * - Version checking: Per-SDK GitHub API queries cached server-side (72h Redis, refreshed every 6 hours)
 * - Smart semver: Contextual thresholds
 */

const DEVICE_CONTEXT_CONFIG = {
    mobileSDKs: ['posthog-ios', 'posthog-android', 'posthog-flutter', 'posthog-react-native'] as SdkType[],
    desktopSDKs: [
        'web',
        'posthog-node',
        'posthog-python',
        'posthog-php',
        'posthog-ruby',
        'posthog-go',
        'posthog-dotnet',
        'posthog-elixir',
    ] as SdkType[],
    // Age-based outdated detection depends on mobile/desktop
    // We're more lenient with mobile versions because it's harder to keep them up to date
    // Arbitrary threshold for now, 4 months for desktop, 6 months for mobile
    ageThresholds: { desktop: 16, mobile: 24 },
} as const

export const sidePanelSdkDoctorLogic = kea<sidePanelSdkDoctorLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSdkDoctorLogic']),

    actions({
        snoozeSdkDoctor: true,
        unsnooze: true,
    }),

    reducers(() => ({
        snoozedUntil: [
            null as string | null,
            { persist: true },
            {
                snoozeSdkDoctor: () => new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
                unsnooze: () => null,
            },
        ],
    })),

    loaders(() => ({
        sdkVersions: [
            null as Record<SdkType, SdkVersionInfo> | null,
            {
                loadSdkVersions: async (): Promise<Record<SdkType, SdkVersionInfo> | null> => {
                    try {
                        const response = await api.get<Record<SdkType, SdkVersionInfo>>('api/sdk_versions/')

                        return response
                    } catch (error) {
                        console.error('Error loading SDK versions:', error)
                        return null
                    }
                },
            },
        ],
        teamSdkVersions: [
            null as TeamSdkVersionsInfo | null,
            {
                loadTeamSdkVersions: async ({
                    forceRefresh,
                }: { forceRefresh?: boolean } = {}): Promise<TeamSdkVersionsInfo | null> => {
                    const endpoint =
                        forceRefresh === true ? 'api/team_sdk_versions/?force_refresh=true' : 'api/team_sdk_versions/'

                    try {
                        const response = await api.get<{ sdk_versions: TeamSdkVersionsInfo; cached: boolean }>(endpoint)
                        return response.sdk_versions
                    } catch (error) {
                        console.error('Error loading team SDK versions:', error)
                        return null
                    }
                },
            },
        ],
    })),

    selectors({
        sdkVersionsMap: [
            (s) => [s.sdkVersions, s.teamSdkVersions],
            (
                sdkVersions: Record<SdkType, SdkVersionInfo>,
                teamSdkVersions: TeamSdkVersionsInfo
            ): AugmentedTeamSdkVersionsInfo => {
                if (!sdkVersions || !teamSdkVersions) {
                    return {}
                }

                return Object.fromEntries(
                    Object.entries(teamSdkVersions).map(([sdkType, teamSdkVersion]) => {
                        const sdkVersion = sdkVersions[sdkType as SdkType]
                        const isSingleVersion = teamSdkVersion.length === 1
                        const releasesInfo = teamSdkVersion.map((version) =>
                            computeAugmentedInfoRelease(sdkType as SdkType, version, sdkVersion, isSingleVersion)
                        )

                        return [
                            sdkType,
                            {
                                isOutdated: releasesInfo[0]!.isOutdated,
                                isOld: releasesInfo[0]!.isOld,
                                needsUpdating: releasesInfo[0]!.needsUpdating,
                                currentVersion: releasesInfo[0]!.version,
                                allReleases: releasesInfo,
                            },
                        ]
                    })
                )
            },
        ],

        needsUpdatingCount: [
            (s) => [s.sdkVersionsMap],
            (sdkVersionsMap: AugmentedTeamSdkVersionsInfo): number => {
                return Object.values(sdkVersionsMap).filter((sdk) => sdk.needsUpdating).length
            },
        ],

        needsAttention: [
            (s) => [s.sdkVersionsMap, s.needsUpdatingCount, s.snoozedUntil],
            (
                sdkVersionsMap: AugmentedTeamSdkVersionsInfo,
                needsUpdatingCount: number,
                snoozedUntil: string | null
            ): boolean => {
                // If snoozed, we don't need attention to this
                if (snoozedUntil !== null) {
                    return false
                }

                // If there are no SDKs - unlikely, but it happens just after onboarding - we don't need attention at all
                const teamSdkCount = Object.values(sdkVersionsMap).length
                if (teamSdkCount === 0) {
                    return false
                }

                // Let's call their attention if at least half of their SDKs are outdated
                // It's unlikely for people to have more than 3 SDKs, but let's be safe
                // and handle it very generically.
                //
                // | Outdated SDKs \ Total SDKs |  1  |  2  |  3  |  4  |  5  |
                // |----------------------------|-----|-----|-----|-----|-----|
                // |                0           |  NO |  NO |  NO |  NO |  NO |
                // |                1           | YES | YES |  NO |  NO |  NO |
                // |                2           |     | YES | YES | YES |  NO |
                // |                3           |     |     | YES | YES | YES |
                // |                4           |     |     |     | YES | YES |
                // |                5           |     |     |     |     | YES |
                return needsUpdatingCount >= Math.ceil(teamSdkCount / 2)
            },
        ],

        sdkHealth: [
            (s) => [s.needsAttention, s.needsUpdatingCount],
            (needsAttention: boolean, needsUpdatingCount: number): SdkHealthStatus => {
                // If there's need for attention, then it's automatically marked as danger
                if (needsAttention) {
                    return 'danger'
                }

                // If there's no need for attention, but there are outdated SDKs, then it's marked as warning
                if (needsUpdatingCount >= 1) {
                    return 'warning'
                }

                // Else, we're in a healthy state
                return 'success'
            },
        ],

        hasErrors: [
            (s) => [s.sdkVersions, s.sdkVersionsLoading, s.teamSdkVersions, s.teamSdkVersionsLoading],
            (
                sdkVersions: Record<SdkType, SdkVersionInfo> | null,
                sdkVersionsLoading: boolean,
                teamSdkVersions: TeamSdkVersionsInfo | null,
                teamSdkVersionsLoading: boolean
            ): boolean => {
                return (
                    (!sdkVersionsLoading && sdkVersions === null) ||
                    (!teamSdkVersionsLoading && teamSdkVersions === null)
                )
            },
        ],
    }),

    listeners({
        snoozeSdkDoctor: () => {
            lemonToast.success('SDK Doctor snoozed for 30 days')
        },
    }),

    afterMount(({ actions, values }) => {
        actions.loadTeamSdkVersions()
        actions.loadSdkVersions()

        if (values.snoozedUntil && new Date(values.snoozedUntil) < new Date()) {
            actions.unsnooze()
        }
    }),
])

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
 *   - isOld: Whether version is outdated by age alone (for "Old" badge)
 *   - deviceContext: Device platform category (mobile/desktop/mixed)
 *   - error: Error message if version parsing fails
 */
function computeAugmentedInfoRelease(
    type: SdkType,
    version: TeamSdkVersionInfo,
    sdkVersion: SdkVersionInfo,
    isSingleVersion: boolean = false
): AugmentedTeamSdkVersionsInfoRelease {
    try {
        // Parse versions for comparison
        const currentVersionParsed = parseVersion(version.lib_version)
        const latestVersionParsed = parseVersion(sdkVersion.latestVersion)

        // Check if versions differ
        const diff = diffVersions(latestVersionParsed, currentVersionParsed)

        // Count number of versions behind by estimating based on semantic version difference
        let releasesBehind = 0
        if (diff) {
            if (diff.kind === 'major') {
                releasesBehind = diff.diff * 100 // Major version differences are significant
            } else if (diff.kind === 'minor') {
                releasesBehind = diff.diff * 10 // Minor versions represent normal releases
            } else if (diff.kind === 'patch') {
                releasesBehind = diff.diff
            }
        }

        // Age-based analysis
        const deviceContext = determineDeviceContext(type)
        const releaseDates = sdkVersion.releaseDates
        const releaseDate: string | undefined = releaseDates[version.lib_version]

        let daysSinceRelease: number | undefined
        let isOld = false

        if (releaseDate) {
            daysSinceRelease = calculateVersionAge(releaseDate)
            const weeksOld = daysSinceRelease / 7

            // Age-based outdated detection depends on mobile/desktop
            // We're more lenient with mobile versions because it's harder to keep them up to date
            const ageThreshold =
                deviceContext === 'desktop'
                    ? DEVICE_CONTEXT_CONFIG.ageThresholds.desktop
                    : DEVICE_CONTEXT_CONFIG.ageThresholds.mobile
            isOld = releasesBehind > 0 && weeksOld > ageThreshold
        }

        // Grace period: Don't flag versions released <7 days ago (even if major version behind)
        // This gives our team time to fix any issues with recent releases before we nag them about new releases
        //
        // NOTE: If daysSinceRelease is undefined (e.g., failed releases not in GitHub),
        // we continue with release count logic only - this is intentional
        let isRecentRelease = false
        const GRACE_PERIOD_DAYS = 7

        if (daysSinceRelease !== undefined) {
            isRecentRelease = daysSinceRelease < GRACE_PERIOD_DAYS
        }

        let isOutdated = false

        // Single version case: only warn if >30 days old to avoid false positives after upgrades
        if (isSingleVersion && diff) {
            const ONE_MONTH_IN_DAYS = 30
            isOutdated = daysSinceRelease !== undefined && daysSinceRelease > ONE_MONTH_IN_DAYS
        } else if (isRecentRelease) {
            isOutdated = false
        } else if (diff) {
            switch (diff.kind) {
                case 'major':
                    // Major version behind (e.g. 1.x -> 2.x): Always flag as outdated
                    isOutdated = true
                    break
                case 'minor':
                    // Minor version behind (e.g. 1.2.x -> 1.5.x): Flag if 3+ minors behind OR >6 months old
                    const sixMonthsInDays = 180
                    const isMinorOutdatedByCount = diff.diff >= 3
                    const isMinorOutdatedByAge = daysSinceRelease !== undefined && daysSinceRelease > sixMonthsInDays
                    isOutdated = isMinorOutdatedByCount || isMinorOutdatedByAge
                    break
                case 'patch':
                    // Patch version behind (e.g. 1.2.3 -> 1.2.7) is never outdated
                    isOutdated = false
                    break
            }
        }

        return {
            type,
            version: version.lib_version,
            maxTimestamp: version.max_timestamp,
            count: version.count,
            isOutdated,
            isOld, // Returned separately for "Old" badge in UI
            needsUpdating: isOutdated || isOld,
            releaseDate,
            daysSinceRelease,
            latestVersion: sdkVersion.latestVersion,
        }
    } catch {
        // If we can't parse the versions, return error state
        return {
            type,
            version: version.lib_version,
            maxTimestamp: version.max_timestamp,
            count: version.count,
            isOutdated: false,
            isOld: false,
            needsUpdating: false,
            releaseDate: undefined,
            daysSinceRelease: undefined,
            latestVersion: sdkVersion.latestVersion,
        }
    }
}

/**
 * Calculate the age of a version in days based on its release date
 *
 * @param releaseDate - ISO date string when the version was released
 * @returns Number of days since the release
 */
function calculateVersionAge(releaseDate: string): number {
    const release = new Date(releaseDate)
    const now = new Date()
    return Math.floor((now.getTime() - release.getTime()) / (1000 * 60 * 60 * 24))
}

/**
 * Determine the device context (mobile/desktop/mixed) for an SDK type
 *
 * @param sdkType - The SDK type to categorize
 * @returns 'mobile', 'desktop', or 'mixed' based on SDK type
 */
function determineDeviceContext(sdkType: SdkType): 'mobile' | 'desktop' | 'mixed' {
    if (DEVICE_CONTEXT_CONFIG.mobileSDKs.includes(sdkType)) {
        return 'mobile'
    }
    if (DEVICE_CONTEXT_CONFIG.desktopSDKs.includes(sdkType)) {
        return 'desktop'
    }

    return 'mixed'
}
