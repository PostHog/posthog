import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { isWebAnalyticsAchievementsEnabled } from './gating'

describe('isWebAnalyticsAchievementsEnabled', () => {
    const flagsOn: FeatureFlagsSet = {
        [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
        [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'hybrid',
    }

    it.each<[string, FeatureFlagsSet, boolean | undefined, boolean]>([
        ['flag on, opted in', flagsOn, false, true],
        ['flag on, opt-out not loaded yet', flagsOn, undefined, true],
        ['flag on but opted out', flagsOn, true, false],
        ['flag off', {}, false, false],
        [
            'flag on but in experiment control arm',
            {
                [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
                [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'control',
            },
            false,
            false,
        ],
    ])('%s', (_label, flags, optedOut, expected) => {
        expect(isWebAnalyticsAchievementsEnabled(flags, optedOut)).toBe(expected)
    })
})
