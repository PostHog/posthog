import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { isPrewarmEnabled } from './flags'

describe('heatmap flags', () => {
    it.each([
        ['boolean rollout is enabled', true, true],
        ['experiment test arm is enabled', 'test', true],
        ['experiment control arm is disabled', 'control', false],
        ['boolean off is disabled', false, false],
        ['unset flag is disabled', undefined, false],
    ])('isPrewarmEnabled: %s', (_name, flagValue: boolean | string | undefined, expected: boolean) => {
        const featureFlags: FeatureFlagsSet = { [FEATURE_FLAGS.HEATMAPS_SCREENSHOT_PREWARM]: flagValue }
        expect(isPrewarmEnabled(featureFlags)).toBe(expected)
    })
})
