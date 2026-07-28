import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { resolveForceWizardArm } from './onboardingEventUsageLogic'

describe('onboardingEventUsageLogic', () => {
    describe('resolveForceWizardArm', () => {
        it.each([
            // Unset/boolean/unknown must resolve to null, never 'control': collapsing never-enrolled
            // users into control pollutes the cohort and biases the readout toward "no effect".
            ['an unset flag', {}, null],
            ['a boolean flag value', { [FEATURE_FLAGS.ONBOARDING_FORCE_WIZARD]: true }, null],
            ['an unregistered variant', { [FEATURE_FLAGS.ONBOARDING_FORCE_WIZARD]: 'something_else' }, null],
            ['the control arm', { [FEATURE_FLAGS.ONBOARDING_FORCE_WIZARD]: 'control' }, 'control'],
            ['the test arm', { [FEATURE_FLAGS.ONBOARDING_FORCE_WIZARD]: 'test' }, 'test'],
        ])('resolves %s', (_name, flags, expected) => {
            expect(resolveForceWizardArm(flags as FeatureFlagsSet)).toBe(expected)
        })
    })
})
