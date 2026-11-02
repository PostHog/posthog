import posthog from 'posthog-js'

import type { OnboardingStepKey } from '~/types'

import type { OnboardingFlowVariant } from './types'

// pinned: event property values. Onboarding funnel insights filter and break down on these, so
// the default flow keeps the values it sent while it was one of two experiment arms. `entry_point`
// rides along with every funnel event, not only `started`, so a breakdown by it stays populated.
export const ONBOARDING_EVENT_PROPS = {
    version: 1,
    flow_variant: 'legacy',
    entry_point: 'product_selection',
} as const

const EVENT_PROPS: Record<OnboardingFlowVariant, Record<string, string | number>> = {
    default: ONBOARDING_EVENT_PROPS,
    // pinned: event property values, see ONBOARDING_EVENT_PROPS.
    simple: { version: 1, flow_variant: 'simple', entry_point: 'simple_onboarding' },
}

export function reportOnboardingStarted(flowVariant: OnboardingFlowVariant): void {
    posthog.capture('onboarding started', EVENT_PROPS[flowVariant])
}

export function reportOnboardingCompleted(productKey: string, flowVariant: OnboardingFlowVariant): void {
    posthog.capture('onboarding completed', {
        product_key: productKey,
        ...EVENT_PROPS[flowVariant],
    })
}

export function reportOnboardingStepCompleted(
    stepKey: OnboardingStepKey,
    flowVariant: OnboardingFlowVariant,
    productKey?: string
): void {
    posthog.capture('onboarding step completed', {
        step_key: stepKey,
        // Optional — only set when the caller knows which product owns the step.
        // Lets dashboards split step funnels by product without joining elsewhere.
        ...(productKey ? { product_key: productKey } : {}),
        ...EVENT_PROPS[flowVariant],
    })
}

export function reportOnboardingStepSkipped(
    stepKey: OnboardingStepKey,
    flowVariant: OnboardingFlowVariant,
    productKey?: string
): void {
    posthog.capture('onboarding step skipped', {
        step_key: stepKey,
        ...(productKey ? { product_key: productKey } : {}),
        ...EVENT_PROPS[flowVariant],
    })
}
