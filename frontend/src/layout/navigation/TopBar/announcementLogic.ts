import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'

import type { announcementLogicType } from './announcementLogicType'

export enum AnnouncementType {
    CloudFlag = 'CloudFlag',
}

export const DEFAULT_CLOUD_ANNOUNCEMENT =
    "We're experiencing technical difficulties. Check [status.posthog.com](https://status.posthog.com) for updates."

export const announcementLogic = kea<announcementLogicType>([
    path(['layout', 'navigation', 'TopBar', 'announcementLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
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
        shownAnnouncementType: [
            (s) => [router.selectors.location, s.relevantAnnouncementType, s.closed, s.persistedClosedAnnouncements],
            ({ pathname }, relevantAnnouncementType, closed, persistedClosedAnnouncements): AnnouncementType | null => {
                if (
                    closed ||
                    (relevantAnnouncementType && persistedClosedAnnouncements[relevantAnnouncementType]) || // hide if already closed
                    pathname.includes('/onboarding') ||
                    pathname.includes('/products') // hide during the onboarding phase
                ) {
                    return null
                }
                return relevantAnnouncementType
            },
        ],
        relevantAnnouncementType: [
            (s) => [s.cloudAnnouncement],
            (cloudAnnouncement): AnnouncementType | null => {
                if (cloudAnnouncement) {
                    return AnnouncementType.CloudFlag
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
