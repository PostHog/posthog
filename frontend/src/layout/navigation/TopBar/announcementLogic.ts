import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'

import type { announcementLogicType } from './announcementLogicType'

export const DEFAULT_CLOUD_ANNOUNCEMENT =
    "We're experiencing technical difficulties. Check [status.posthog.com](https://status.posthog.com) for updates."

export const announcementLogic = kea<announcementLogicType>([
    path(['layout', 'navigation', 'TopBar', 'announcementLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        hideAnnouncement: true,
    }),
    reducers({
        closed: [
            false,
            {
                hideAnnouncement: () => true,
            },
        ],
    }),
    selectors({
        showAnnouncement: [
            (s) => [router.selectors.location, s.cloudAnnouncement, s.closed],
            ({ pathname }, cloudAnnouncement, closed): boolean => {
                if (
                    !cloudAnnouncement ||
                    closed ||
                    pathname.includes('/onboarding') ||
                    pathname.includes('/products') // hide during the onboarding phase
                ) {
                    return false
                }
                return true
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
