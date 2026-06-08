import { Tooltip } from '@posthog/lemon-ui'

import { getExternalAIProvidersTooltipTitle } from 'scenes/settings/organization/aiConsentCopy'
import { OrganizationAI } from 'scenes/settings/organization/OrgAI'

/**
 * AI data-processing consent, surfaced on the first onboarding step so new orgs
 * see — and can confirm — PostHog AI up front rather than hitting the opt-in as
 * friction later. Reuses the org settings toggle so copy and persistence stay in
 * one place; the toggle is org-scoped and defaults on.
 */
export function OnboardingAIConsent(): JSX.Element {
    return (
        <div className="rounded-lg border border-primary p-4 mb-2">
            <h3 className="mb-1 text-base font-semibold">PostHog AI</h3>
            <p className="text-secondary mb-3">
                PostHog AI features, such as the PostHog AI chat, use{' '}
                <Tooltip title={getExternalAIProvidersTooltipTitle()}>
                    <dfn>external AI services</dfn>
                </Tooltip>{' '}
                for data analysis. <strong>Your data will not be used for training third-party models.</strong>
            </p>
            <OrganizationAI />
        </div>
    )
}
