import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getFramerInstallSteps } from '../product-analytics/framer'
import { StepDefinition } from '../steps'

export const getFramerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getFramerInstallSteps(ctx),
        {
            title: 'Send events',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const FramerInstallation = createInstallation(getFramerSteps)
