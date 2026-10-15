import posthog from 'posthog-js'

import { OnboardingStepKey } from '~/types'

// pinned: event property values. Onboarding funnel insights filter and break down on these, so
// they keep the values the flow sent while it was one of two experiment arms. `entry_point` rides
// along with every funnel event, not only `started`, so a breakdown by it stays populated.
export const ONBOARDING_EVENT_PROPS = {
    version: 1,
    flow_variant: 'legacy',
    entry_point: 'product_selection',
} as const

export function reportOnboardingStarted(): void {
    posthog.capture('onboarding started', ONBOARDING_EVENT_PROPS)
}

export function reportOnboardingCompleted(productKey: string): void {
    posthog.capture('onboarding completed', {
        product_key: productKey,
        ...ONBOARDING_EVENT_PROPS,
    })
}

export function reportOnboardingStepCompleted(stepKey: OnboardingStepKey, productKey?: string): void {
    posthog.capture('onboarding step completed', {
        step_key: stepKey,
        // Optional — only set when the caller knows which product owns the step.
        // Lets dashboards split step funnels by product without joining elsewhere.
        ...(productKey ? { product_key: productKey } : {}),
        ...ONBOARDING_EVENT_PROPS,
    })
}

export function reportOnboardingStepSkipped(stepKey: OnboardingStepKey, productKey?: string): void {
    posthog.capture('onboarding step skipped', {
        step_key: stepKey,
        ...(productKey ? { product_key: productKey } : {}),
        ...ONBOARDING_EVENT_PROPS,
    })
}
