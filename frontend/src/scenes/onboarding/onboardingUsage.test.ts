import posthog from 'posthog-js'

import { SELF_DRIVING_ONBOARDING_EVENT_PROPS } from './onboardingEventUsageLogic'
import {
    reportOnboardingCompleted,
    reportOnboardingStarted,
    reportOnboardingStepCompleted,
    reportOnboardingStepSkipped,
    type OnboardingEventProperties,
} from './onboardingUsage'

describe('onboardingUsage', () => {
    const cases: [string, OnboardingEventProperties | undefined, string, string, 1 | 2][] = [
        ['legacy', undefined, 'product_selection', 'legacy', 1],
        ['self-driving', SELF_DRIVING_ONBOARDING_EVENT_PROPS, 'welcome', 'context_first', 2],
    ]

    it.each(cases)('keeps the %s funnel event properties', (_name, properties, entryPoint, variant, version) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()

        reportOnboardingStarted(properties)
        reportOnboardingStepCompleted('install', undefined, properties)
        reportOnboardingStepSkipped('install', undefined, properties)
        reportOnboardingCompleted('product_analytics', properties)

        const sharedProperties = { entry_point: entryPoint, flow_variant: variant, version }
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
        capture.mockRestore()
    })
})
