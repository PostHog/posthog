import { kea } from 'kea'
import { FEATURE_FLAGS } from '../../lib/constants'
import { featureFlagLogic } from '../../lib/logic/featureFlagLogic'
import { lemonadeLogicType } from './lemonadeLogicType'

export const lemonadeLogic = kea<lemonadeLogicType>({
    connect: {
        values: [featureFlagLogic, ['featureFlags']],
    },
    actions: {
        hideAnnouncement: true,
    },
    reducers: {
        isAnnouncementHidden: [
            false,
            {
                hideAnnouncement: () => true,
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
