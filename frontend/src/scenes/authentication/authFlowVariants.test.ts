import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { type AuthFlowVariant, resolveAuthFlowVariant } from './authFlowVariants'

describe('resolveAuthFlowVariant', () => {
    // A missing flag must fall back to the legacy pages — otherwise a freshly spun-up
    // local stack (no flag defined) would render the unfinished redesign screens.
    it('defaults to legacy when the flag does not exist', () => {
        expect(resolveAuthFlowVariant({})).toEqual('legacy')
    })

    it.each<[string, FeatureFlagsSet, AuthFlowVariant]>([
        ['flag absent', {}, 'legacy'],
        ['flag is boolean true', { [FEATURE_FLAGS.AUTH_FLOW_VARIANT]: true }, 'legacy'],
        ['flag is boolean false', { [FEATURE_FLAGS.AUTH_FLOW_VARIANT]: false }, 'legacy'],
        ['flag is an unknown variant string', { [FEATURE_FLAGS.AUTH_FLOW_VARIANT]: 'something-else' }, 'legacy'],
        ['flag is the legacy variant', { [FEATURE_FLAGS.AUTH_FLOW_VARIANT]: 'legacy' }, 'legacy'],
        [
            'flag is the redesign variant',
            { [FEATURE_FLAGS.AUTH_FLOW_VARIANT]: 'redesign-2026-06-02' },
            'redesign-2026-06-02',
        ],
    ])('resolves %s to %s', (_description, featureFlags, expected) => {
        expect(resolveAuthFlowVariant(featureFlags)).toEqual(expected)
    })
})
