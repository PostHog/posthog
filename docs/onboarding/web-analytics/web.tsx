import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getWebInstallSteps } from '../product-analytics/web'
import { StepDefinition } from '../steps'

export const getWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getWebInstallSteps(ctx),
        {
            title: 'Send events',
            badge: 'recommended',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const WebInstallation = createInstallation(getWebSteps)
