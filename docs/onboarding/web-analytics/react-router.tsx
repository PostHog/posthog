import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactRouterSteps as getReactRouterStepsPA } from '../product-analytics/react-router'
import { StepDefinition } from '../steps'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    const paSteps = getReactRouterStepsPA(ctx)
    const webAnalyticsSteps = paSteps.map((step) => {
        if (step.title === 'Send events') {
            return {
                ...step,
                content: <>{WebFinalSteps && <WebFinalSteps />}</>,
            }
        }
        return step
    })

    return webAnalyticsSteps
}

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
