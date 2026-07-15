import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { sdkHealthReportRetrieve } from 'products/growth/frontend/generated/api'
import type { SdkAssessmentApi, SdkHealthReportApi } from 'products/growth/frontend/generated/api.schemas'

import type { sdkHealthLogicType } from './sdkHealthLogicType'

export type SdkType = SdkAssessmentApi['lib']

// Small helper to define what our versions look like
export type SdkVersion = `${string}.${string}.${string}`

/**
 * Overall health status for SDK version monitoring
 */
export type SdkHealthStatus = SdkHealthReportApi['health']

// All outdatedness heuristics live in products/growth/backend/sdk_health.py. The frontend adapts
// the generated API response for display, but does not recompute health.
export type OutdatedTrafficAlert = {
    version: string
    thresholdPercent: number
}

// --- Camel-cased shapes the UI components consume (adapted from the backend report) ----------

export type AugmentedTeamSdkVersionsInfoRelease = {
    type: SdkType
    version: string
    maxTimestamp: string
    count: number
    latestVersion: string
    releaseDate: string | undefined
    releasedAgo: string | undefined
    daysSinceRelease: number | undefined
    isOutdated: boolean
    isOld: boolean
    needsUpdating: boolean
    migrationRequired: boolean
    isCurrentOrNewer: boolean
    statusReason: string
    sqlQuery: string
    activityPageUrl: string
}

export type AugmentedTeamSdkVersionsInfo = {
    [key in SdkType]?: {
        isOutdated: boolean
        isOld: boolean
        needsUpdating: boolean
        migrationRequired: boolean
        currentVersion: string
        severity: 'none' | 'warning' | 'danger'
        banners: string[]
        allReleases: AugmentedTeamSdkVersionsInfoRelease[]
        outdatedTrafficAlerts: OutdatedTrafficAlert[]
    }
}

/**
 * SDK Health - PostHog SDK Health Monitoring
 *
 * Detects installed SDKs and their versions across a team's events and surfaces a pre-digested
 * health report computed entirely by the backend (see products/growth/backend/sdk_health.py).
 *
 * Data flow:
 * - Team SDK detections + GitHub latest versions are cached server-side and refreshed by the
 *   Temporal `sdk_outdated` health check.
 * - The `report` endpoint applies the outdatedness heuristics and returns the assessment below.
 */

export const sdkHealthLogic = kea<sdkHealthLogicType>([
    path(['scenes', 'onboarding', 'shared', 'sdkHealth', 'sdkHealthLogic']),

    connect(() => ({
        values: [preflightLogic, ['isCloudOrDev'], teamLogic, ['currentTeamId']],
    })),

    actions({
        snoozeSdkHealth: true,
        unsnooze: true,
    }),

    reducers(() => ({
        snoozedUntil: [
            null as string | null,
            { persist: true },
            {
                snoozeSdkHealth: () => new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
                unsnooze: () => null,
            },
        ],
    })),

    loaders(({ values }) => ({
        report: [
            null as SdkHealthReportApi | null,
            {
                loadReport: async (options?: { forceRefresh?: boolean }): Promise<SdkHealthReportApi | null> => {
                    // Skip while the team is still loading — firing against /projects/null/ 404s and
                    // would leave the scene stuck in an error state with no automatic retry.
                    if (!values.currentTeamId) {
                        return null
                    }
                    try {
                        return await sdkHealthReportRetrieve(
                            String(values.currentTeamId),
                            options?.forceRefresh === true ? { force_refresh: true } : undefined
                        )
                    } catch (error) {
                        console.error('Error loading SDK health report', error)
                        return null
                    }
                },
            },
        ],
    })),

    selectors({
        augmentedData: [
            (s) => [s.report],
            (report: SdkHealthReportApi | null): AugmentedTeamSdkVersionsInfo => {
                if (!report) {
                    return {}
                }

                return Object.fromEntries(
                    report.sdks.map((sdk) => [
                        sdk.lib,
                        {
                            isOutdated: sdk.is_outdated,
                            isOld: sdk.is_old,
                            needsUpdating: sdk.needs_updating,
                            migrationRequired: sdk.migration_required,
                            currentVersion: sdk.latest_version,
                            severity: sdk.severity,
                            banners: sdk.banners,
                            outdatedTrafficAlerts: sdk.outdated_traffic_alerts.map((alert) => ({
                                version: alert.version,
                                thresholdPercent: alert.threshold_percent,
                            })),
                            allReleases: sdk.releases.map(
                                (release): AugmentedTeamSdkVersionsInfoRelease => ({
                                    type: sdk.lib,
                                    version: release.version,
                                    maxTimestamp: release.max_timestamp,
                                    count: release.count,
                                    latestVersion: sdk.latest_version,
                                    releaseDate: release.release_date ?? undefined,
                                    releasedAgo: release.released_ago ?? undefined,
                                    daysSinceRelease: release.days_since_release ?? undefined,
                                    isOutdated: release.is_outdated,
                                    isOld: release.is_old,
                                    needsUpdating: release.needs_updating,
                                    migrationRequired: sdk.migration_required,
                                    isCurrentOrNewer: release.is_current_or_newer,
                                    statusReason: release.status_reason,
                                    sqlQuery: release.sql_query,
                                    activityPageUrl: release.activity_page_url,
                                })
                            ),
                        },
                    ])
                )
            },
        ],

        needsUpdatingCount: [
            (s) => [s.report],
            (report: SdkHealthReportApi | null): number => report?.needs_updating_count ?? 0,
        ],

        needsAttention: [
            (s) => [s.report, s.snoozedUntil],
            (report: SdkHealthReportApi | null, snoozedUntil: string | null): boolean => {
                if (snoozedUntil !== null) {
                    return false
                }
                return report?.overall_health === 'needs_attention'
            },
        ],

        sdkHealth: [
            (s) => [s.report],
            (report: SdkHealthReportApi | null): SdkHealthStatus => report?.health ?? 'success',
        ],

        hasErrors: [
            (s) => [s.report, s.reportLoading],
            (report: SdkHealthReportApi | null, reportLoading: boolean): boolean => {
                return !reportLoading && report === null
            },
        ],
    }),

    listeners({
        snoozeSdkHealth: () => {
            lemonToast.success('SDK Health snoozed for 30 days')
        },
    }),

    subscriptions(({ actions, values }) => ({
        // If the team was still loading when the scene mounted (currentTeamId null), afterMount's
        // loadReport bailed early — retry once the team id arrives. `oldTeamId === null` targets that
        // real null→id transition specifically, so a fresh mount with the team already present never
        // double-loads.
        currentTeamId: (currentTeamId, oldTeamId) => {
            if (currentTeamId && oldTeamId === null && values.isCloudOrDev) {
                actions.loadReport()
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.isCloudOrDev) {
            return
        }

        actions.loadReport()

        if (values.snoozedUntil && new Date(values.snoozedUntil) < new Date()) {
            actions.unsnooze()
        }
    }),
])
