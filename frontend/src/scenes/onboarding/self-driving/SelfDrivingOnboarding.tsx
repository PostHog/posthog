import './SelfDrivingOnboarding.scss'

import { Logo } from 'lib/brand'

import { ContextOnboarding } from './ContextOnboarding'

/**
 * Host for the self-driving onboarding experience: dotted backdrop, logo, and a centered card that
 * holds the context-first step flow. Selected via `onboardingVariantRegistry` when the
 * `ONBOARDING_FLOW_VARIANT` flag resolves to `'self-driving'`.
 */
export function SelfDrivingOnboarding(): JSX.Element | null {
    return (
        <div className="OnboardingDottedBg min-h-screen flex flex-col items-center justify-center p-4 sm:p-6">
            {/* Logo above the card, group centered (paper-desk positioning). Gradient in light, white in dark. */}
            <span className="block mb-6">
                <Logo size="lg" />
            </span>
            {/* The card chrome and its per-step width live inside ContextOnboarding (so the width can vary
                by step); here we just center it under the logo. */}
            <ContextOnboarding />
        </div>
    )
}
