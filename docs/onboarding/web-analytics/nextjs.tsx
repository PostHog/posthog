import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getNextJSInstallSteps } from '../product-analytics/nextjs'
import { StepDefinition } from '../steps'

export const getNextJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getNextJSInstallSteps(ctx),
        {
            title: 'Send events',
            badge: 'recommended',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const NextJSInstallation = createInstallation(getNextJSSteps)
