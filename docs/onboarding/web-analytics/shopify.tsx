import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getShopifyEcommerceStep, getShopifyInstallSteps } from '../product-analytics/shopify'
import { StepDefinition } from '../steps'

export const getShopifySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getShopifyInstallSteps(ctx),
        getShopifyEcommerceStep(ctx),
        {
            title: 'Send events',
            badge: 'recommended' as const,
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const ShopifyInstallation = createInstallation(getShopifySteps)
