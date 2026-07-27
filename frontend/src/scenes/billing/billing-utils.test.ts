import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { getUsageTypeOptions } from './billing-utils'

describe('getUsageTypeOptions', () => {
    it.each<[string, FeatureFlagsSet, boolean]>([
        ['on', { [FEATURE_FLAGS.REPLAY_VISION]: true }, true],
        ['off', { [FEATURE_FLAGS.REPLAY_VISION]: false }, false],
        ['missing', {}, false],
    ])(
        'shows replay vision credits only when the replay-vision flag is on (flag %s)',
        (_name, featureFlags, visible) => {
            const options = getUsageTypeOptions(featureFlags)
            expect(options.some((opt) => opt.key === 'replay_vision_credits_used_in_period')).toBe(visible)
            // the gate never affects other usage types
            expect(options.some((opt) => opt.key === 'event_count_in_period')).toBe(true)
        }
    )
})
