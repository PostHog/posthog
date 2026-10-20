import posthog from 'posthog-js'

import { OnboardingStepKey } from '~/types'

import {
    reportOnboardingCompleted,
    reportOnboardingStarted,
    reportOnboardingStepCompleted,
    reportOnboardingStepSkipped,
} from './onboardingUsage'

describe('onboardingUsage', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('keeps the funnel event properties', () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()

        reportOnboardingStarted()
        reportOnboardingStepCompleted(OnboardingStepKey.INSTALL)
        reportOnboardingStepSkipped(OnboardingStepKey.INSTALL)
        reportOnboardingCompleted('product_analytics')

        const sharedProperties = { entry_point: 'product_selection', flow_variant: 'legacy', version: 1 }
        expect(capture).toHaveBeenNthCalledWith(1, 'onboarding started', sharedProperties)
        expect(capture).toHaveBeenNthCalledWith(2, 'onboarding step completed', {
            step_key: 'install',
            ...sharedProperties,
        })
        expect(capture).toHaveBeenNthCalledWith(3, 'onboarding step skipped', {
            step_key: 'install',
            ...sharedProperties,
        })
        expect(capture).toHaveBeenNthCalledWith(4, 'onboarding completed', {
            product_key: 'product_analytics',
            ...sharedProperties,
        })
    })
})
