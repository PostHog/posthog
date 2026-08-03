import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { getUsageTypeOptions, parseBillingLimitInput } from './billing-utils'

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

describe('parseBillingLimitInput', () => {
    // A typed thousands separator used to reach the billing limit validator as NaN (from
    // `type="number"`'s `valueAsNumber`), which the validator misreported as "not a whole
    // number" even though the digits read as a valid amount. This guards the fix: separators
    // are stripped before parsing, so a value like "1,500" resolves to a real number again.
    it.each([
        ['1,500', 1500],
        ['1500', 1500],
        ['0', 0],
        ['', null],
        ['   ', null],
        ['1.5', 1.5], // fractional input is left to the whole-number validator, not silently rounded
        ['abc', NaN],
    ])('parses %s as %s', (input, expected) => {
        expect(parseBillingLimitInput(input)).toBe(expected)
    })
})
