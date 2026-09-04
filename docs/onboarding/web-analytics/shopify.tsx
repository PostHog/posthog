import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getShopifyInstallSteps } from '../product-analytics/shopify'
import { StepDefinition } from '../steps'

export const getShopifySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getShopifyInstallSteps(ctx),
        {
            title: 'Send events',
            badge: 'recommended' as const,
            content: (
                <>
                    {WebFinalSteps && <WebFinalSteps />}
                    <Markdown>
                        See the [Shopify integration docs](https://posthog.com/docs/libraries/shopify) for tracking
                        checkout events and revenue.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const ShopifyInstallation = createInstallation(getShopifySteps)
