import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getVueInstallSteps } from '../product-analytics/vue'
import { StepDefinition } from '../steps'

export const getVueSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getVueInstallSteps(ctx),
        {
            title: 'Send events',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const VueInstallation = createInstallation(getVueSteps)
