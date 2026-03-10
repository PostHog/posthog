import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getWebSteps as getWebStepsPA } from '../product-analytics/web'
import { StepDefinition } from '../steps'

export const getWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    const paSteps = getWebStepsPA(ctx)

    const webAnalyticsSteps = paSteps.map((step: StepDefinition) => {
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

export const WebInstallation = createInstallation(getWebSteps)
