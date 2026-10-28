import posthog from 'posthog-js'

import { OnboardingStepKey } from '~/types'

import {
    reportOnboardingCompleted,
    reportOnboardingStarted,
    reportOnboardingStepCompleted,
    reportOnboardingStepSkipped,
} from './onboardingUsage'
import type { OnboardingFlowVariant } from './types'

describe('onboardingUsage', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each<[OnboardingFlowVariant, Record<string, unknown>]>([
        ['default', { entry_point: 'product_selection', flow_variant: 'legacy', version: 1 }],
        ['simple', { entry_point: 'simple_onboarding', flow_variant: 'simple', version: 1 }],
    ])('keeps the %s flow funnel event properties', (flowVariant, sharedProperties) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()

        reportOnboardingStarted(flowVariant)
        reportOnboardingStepCompleted(OnboardingStepKey.INSTALL, flowVariant)
        reportOnboardingStepSkipped(OnboardingStepKey.INSTALL, flowVariant)
        reportOnboardingCompleted('product_analytics', flowVariant)

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
