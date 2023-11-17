import { kea, connect, path, actions, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '../navigationLogic'
import posthog from 'posthog-js'

import type { announcementLogicType } from './announcementLogicType'

export enum AnnouncementType {
    Demo = 'Demo',
    CloudFlag = 'CloudFlag',
    NewFeature = 'NewFeature',
    AttentionRequired = 'AttentionRequired',
}

export const DEFAULT_CLOUD_ANNOUNCEMENT =
    "We're experiencing technical difficulties. Check [status.posthog.com](https://status.posthog.com) for updates."

// Switch to `false` if we're not showing a feature announcement. Hard-coded because the announcement needs to be manually updated anyways.
const ShowNewFeatureAnnouncement = false
const ShowAttentionRequiredBanner = false

export const announcementLogic = kea<announcementLogicType>([
    path(['layout', 'navigation', 'TopBar', 'announcementLogic']),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['preflight'],
            userLogic,
            ['user'],
            navigationLogic,
            ['asyncMigrationsOk'],
        ],
    }),
    actions({
        hideAnnouncement: (type: AnnouncementType | null) => ({ type }),
    }),
    reducers({
        persistedClosedAnnouncements: [
            {} as Record<AnnouncementType, boolean>,
            { persist: true },
            {
                hideAnnouncement: (state, { type }) => {
                    // :TRICKY: We don't close cloud announcements forever, just until reload
                    if (!type || type === AnnouncementType.CloudFlag) {
                        return state
                    }
                    return { ...state, [type]: true }
                },
            },
        ],
        closed: [
            false,
            {
                hideAnnouncement: () => true,
            },
        ],
    }),
    selectors({
        closable: [
            (s) => [s.relevantAnnouncementType],
            // The demo announcement is persistent
            (relevantAnnouncementType): boolean => relevantAnnouncementType !== AnnouncementType.Demo,
        ],
        shownAnnouncementType: [
            (s) => [
                router.selectors.location,
                s.relevantAnnouncementType,
                s.closable,
                s.closed,
                s.persistedClosedAnnouncements,
            ],
            (
                { pathname },
                relevantAnnouncementType,
                closable,
                closed,
                persistedClosedAnnouncements
            ): AnnouncementType | null => {
                if (
                    (closable &&
                        (closed ||
                            (relevantAnnouncementType && persistedClosedAnnouncements[relevantAnnouncementType]))) || // hide if already closed
                    pathname.includes('/onboarding') ||
                    pathname.includes('/products') // hide during the onboarding phase
                ) {
                    return null
                }
                return relevantAnnouncementType
            },
        ],
        relevantAnnouncementType: [
            (s) => [s.cloudAnnouncement, s.preflight, s.user, s.asyncMigrationsOk],
            (cloudAnnouncement, preflight, user, asyncMigrationsOk): AnnouncementType | null => {
                if (preflight?.demo) {
                    return AnnouncementType.Demo
                } else if (cloudAnnouncement) {
                    return AnnouncementType.CloudFlag
                } else if (
                    ShowAttentionRequiredBanner &&
                    !asyncMigrationsOk &&
                    (user?.is_staff || (user?.organization?.membership_level ?? 0) >= OrganizationMembershipLevel.Admin)
                ) {
                    return AnnouncementType.AttentionRequired
                } else if (ShowNewFeatureAnnouncement) {
                    return AnnouncementType.NewFeature
                }
                return null
            },
        ],
        cloudAnnouncement: [
            (s) => [s.featureFlags],
            (featureFlags): string | null => {
                const flagPayload = posthog.getFeatureFlagPayload(FEATURE_FLAGS.CLOUD_ANNOUNCEMENT)
                const flagEnabled = featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]

                if (flagEnabled && !flagPayload) {
                    // Default to standard cloud announcement if no payload is set
                    return DEFAULT_CLOUD_ANNOUNCEMENT
                }
                return !!flagPayload && typeof flagPayload === 'string' ? flagPayload : null
            },
        ],
    }),
])
