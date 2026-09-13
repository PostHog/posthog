import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getRemixInstallSteps } from '../product-analytics/remix'
import { StepDefinition } from '../steps'

export const getRemixSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getRemixInstallSteps(ctx),
        {
            title: 'Send events',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const RemixInstallation = createInstallation(getRemixSteps)
