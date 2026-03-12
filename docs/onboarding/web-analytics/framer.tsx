import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getFramerSteps as getFramerStepsPA } from '../product-analytics/framer'
import { StepDefinition } from '../steps'

export const getFramerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getFramerStepsPA(ctx)

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

export const FramerInstallation = createInstallation(getFramerSteps)
