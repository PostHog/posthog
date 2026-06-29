import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { UserType } from '~/types'

import { isWebAnalyticsAchievementsEnabled } from './gating'

describe('isWebAnalyticsAchievementsEnabled', () => {
    const flagsOn: FeatureFlagsSet = {
        [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
        [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'hybrid',
    }
    const optedOut = { web_analytics_achievements_opt_out: true } as UserType
    const optedIn = { web_analytics_achievements_opt_out: false } as UserType

    it.each<[string, FeatureFlagsSet, UserType | null | undefined, boolean]>([
        ['flag on, opted in', flagsOn, optedIn, true],
        ['flag on, no user loaded', flagsOn, undefined, true],
        ['flag on but user opted out', flagsOn, optedOut, false],
        ['flag off', {}, optedIn, false],
        [
            'flag on but in experiment control arm',
            {
                [FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]: true,
                [FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE]: 'control',
            },
            optedIn,
            false,
        ],
    ])('%s', (_label, flags, user, expected) => {
        expect(isWebAnalyticsAchievementsEnabled(flags, user)).toBe(expected)
    })
})
