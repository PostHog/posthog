import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getJSWebSteps as getJSWebStepsPA } from '../product-analytics/js-web'
import { StepDefinition } from '../steps'

export const getJSWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getJSWebStepsPA(ctx)

    // Replace the "Send events" step with web analytics specific content
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

export const JSWebInstallation = createInstallation(getJSWebSteps)
