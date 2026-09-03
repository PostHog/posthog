import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getReactInstallSteps } from '../product-analytics/react'
import { StepDefinition } from '../steps'

export const getReactSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getReactInstallSteps(ctx),
        {
            title: 'Send events',
            badge: 'recommended',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const ReactInstallation = createInstallation(getReactSteps)
