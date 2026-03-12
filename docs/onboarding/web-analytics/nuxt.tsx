import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getNuxtSteps as getNuxtStepsPA } from '../product-analytics/nuxt'
import { StepDefinition } from '../steps'

export const getNuxtSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getNuxtStepsPA(ctx)

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

export const NuxtInstallation = createInstallation(getNuxtSteps)
