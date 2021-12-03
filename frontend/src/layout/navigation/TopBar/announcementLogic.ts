import { kea } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { announcementLogicType } from './announcementLogicType'

export const announcementLogic = kea<announcementLogicType>({
    connect: {
        values: [featureFlagLogic, ['featureFlags']],
    },
    actions: {
        hideAnnouncement: true,
    },
    reducers: {
        isAnnouncementShown: [
            true,
            {
                hideAnnouncement: () => false,
            },
        ],
    },
    selectors: {
        announcementMessage: [
            (s) => [s.featureFlags],
            (featureFlags): string | null => {
                const flagValue = featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]
                return flagValue && typeof flagValue === 'string'
                    ? featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT]
                    : null
            },
        ],
    },
})
