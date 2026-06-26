import './LegacyOnboarding.scss'

import { PostHogLogo } from 'lib/brand/v2'

import { ContextOnboarding } from './ContextOnboarding'

/**
 * Host for the ("legacy") onboarding experience: dotted backdrop, logo, and a centered card that
 * holds the context-first step flow. Selected via `onboardingVariantRegistry`.
 */
export function LegacyOnboarding(): JSX.Element | null {
    return (
        <div className="OnboardingDottedBg min-h-screen flex flex-col items-center justify-center p-4 sm:p-6">
            {/* Logo above the card, group centered (paper-desk positioning). Gradient in light, white in dark. */}
            <span className="block mb-6">
                <PostHogLogo className="h-7 w-auto block dark:hidden sm:h-8" />
                <PostHogLogo variant="mono" color="white" className="h-7 w-auto hidden dark:block sm:h-8" />
            </span>
            {/* Card hugs its content and stays centered. At `sm`+ it gets the panel chrome and is capped to
                the viewport (`max-h`) as a flex column; the flow's middle scrolls internally so the page
                never scrolls. On mobile the chrome drops away (see .OnboardingDottedBg), the cap is lifted,
                and content flows full-bleed. `relative` anchors the flow's back button to the top-left corner. */}
            <div className="relative w-full max-w-xl overflow-hidden p-0 sm:flex sm:flex-col sm:max-h-[calc(100dvh-7rem)] sm:p-8 md:p-10 sm:bg-surface-primary sm:rounded-xl sm:shadow-md sm:border sm:border-primary">
                <ContextOnboarding />
            </div>
        </div>
    )
}
