import posthog from 'posthog-js'

import { OnboardingStepKey } from '~/types'

import type { SelfDrivingOnboardingStepId } from './onboardingEventUsageLogic'

// GROW-89: both onboarding flows fire the same funnel event names during the transition, told apart
// by `version` (1 = legacy, 2 = context-first redesign) and `flow_variant`. Stamping properties
// instead of renaming keeps every existing dashboard and alert on the v1 events working. The
// redesign's v2 events live in `scenes/onboarding/onboardingEventUsageLogic`.
// `entry_point` names the surface the flow starts on. It rides along with every funnel event, not
// only `started`, so a breakdown by entry point stays populated for the whole funnel.
export type OnboardingEntryPoint = 'product_selection' | 'welcome'

export type OnboardingEventProperties = {
    entry_point: OnboardingEntryPoint
    flow_variant: 'context_first' | 'legacy'
    version: 1 | 2
}

export const LEGACY_ONBOARDING_EVENT_PROPS: OnboardingEventProperties = {
    version: 1,
    flow_variant: 'legacy',
    entry_point: 'product_selection',
}

// onboarding
export function reportOnboardingStarted(properties?: OnboardingEventProperties): void {
    posthog.capture('onboarding started', {
        ...LEGACY_ONBOARDING_EVENT_PROPS,
        ...properties,
    })
}

export function reportOnboardingCompleted(productKey: string, properties?: OnboardingEventProperties): void {
    posthog.capture('onboarding completed', {
        product_key: productKey,
        ...LEGACY_ONBOARDING_EVENT_PROPS,
        ...properties,
    })
}

export function reportOnboardingStepCompleted(
    stepKey: OnboardingStepKey | SelfDrivingOnboardingStepId,
    productKey?: string,
    properties?: OnboardingEventProperties
): void {
    posthog.capture('onboarding step completed', {
        step_key: stepKey,
        // Optional — only set when the caller knows which product owns the step.
        // Lets dashboards split step funnels by product without joining elsewhere.
        ...(productKey ? { product_key: productKey } : {}),
        ...LEGACY_ONBOARDING_EVENT_PROPS,
        ...properties,
    })
}

export function reportOnboardingStepSkipped(
    stepKey: OnboardingStepKey | SelfDrivingOnboardingStepId,
    productKey?: string,
    properties?: OnboardingEventProperties
): void {
    posthog.capture('onboarding step skipped', {
        step_key: stepKey,
        ...(productKey ? { product_key: productKey } : {}),
        ...LEGACY_ONBOARDING_EVENT_PROPS,
        ...properties,
    })
}
