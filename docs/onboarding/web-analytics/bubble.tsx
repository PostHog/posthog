import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getBubbleInstallSteps } from '../product-analytics/bubble'
import { StepDefinition } from '../steps'

export const getBubbleSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getBubbleInstallSteps(ctx),
        {
            title: 'Send events',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const BubbleInstallation = createInstallation(getBubbleSteps)
