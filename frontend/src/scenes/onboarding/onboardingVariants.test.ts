import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { onboardingVariantChrome, resolveOnboardingFlowVariant } from './onboardingVariants'

describe('onboardingVariants', () => {
    describe('resolveOnboardingFlowVariant', () => {
        it('falls back to control when the flag is not set', () => {
            expect(resolveOnboardingFlowVariant({} as FeatureFlagsSet)).toBe('control')
        })

        it('falls back to control when the flag resolves to a boolean', () => {
            expect(
                resolveOnboardingFlowVariant({ [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: true } as FeatureFlagsSet)
            ).toBe('control')
        })

        it('returns the variant string when set to a named variant', () => {
            expect(
                resolveOnboardingFlowVariant({
                    [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: 'some_future_variant',
                } as FeatureFlagsSet)
            ).toBe('some_future_variant')
        })
    })

    describe('onboardingVariantChrome', () => {
        it('control keeps the minimal top bar', () => {
            expect(onboardingVariantChrome('control')).toBe('minimal')
        })

        it('defaults to minimal for an unregistered variant', () => {
            expect(onboardingVariantChrome('not_a_real_variant')).toBe('minimal')
        })
    })
})
