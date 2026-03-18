import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getShopifySteps as getShopifyStepsPA } from '../product-analytics/shopify'
import { StepDefinition } from '../steps'

export const getShopifySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getShopifyStepsPA(ctx)

    // Replace the "Verify installation" step with web analytics specific content
    const webAnalyticsSteps = paSteps.map((step) => {
        if (step.title === 'Verify installation') {
            return {
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
            }
        }
        return step
    })

    return webAnalyticsSteps
}

export const ShopifyInstallation = createInstallation(getShopifySteps)
