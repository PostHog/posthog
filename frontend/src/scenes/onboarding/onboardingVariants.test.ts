import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { onboardingVariantChrome, resolveOnboardingFlowVariant } from './onboardingVariants'

describe('onboardingVariants', () => {
    describe('resolveOnboardingFlowVariant', () => {
        it('falls back to legacy when the flag is not set', () => {
            expect(resolveOnboardingFlowVariant({} as FeatureFlagsSet)).toBe('legacy')
        })

        it('falls back to legacy when the flag resolves to a boolean', () => {
            expect(
                resolveOnboardingFlowVariant({ [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: true } as FeatureFlagsSet)
            ).toBe('legacy')
        })

        it('maps the original control flag value to legacy', () => {
            expect(
                resolveOnboardingFlowVariant({ [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: 'control' } as FeatureFlagsSet)
            ).toBe('legacy')
        })

        it('returns redesign when the flag selects it', () => {
            expect(
                resolveOnboardingFlowVariant({ [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: 'redesign' } as FeatureFlagsSet)
            ).toBe('redesign')
        })

        it('falls back to legacy for an unregistered variant', () => {
            expect(
                resolveOnboardingFlowVariant({
                    [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: 'some_future_variant',
                } as FeatureFlagsSet)
            ).toBe('legacy')
        })
    })

    describe('onboardingVariantChrome', () => {
        it('legacy keeps the minimal top bar', () => {
            expect(onboardingVariantChrome('legacy')).toBe('minimal')
        })

        it('redesign keeps the minimal top bar', () => {
            expect(onboardingVariantChrome('redesign')).toBe('minimal')
        })
    })
})
