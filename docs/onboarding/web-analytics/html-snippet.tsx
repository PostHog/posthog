import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getHTMLSnippetSteps as getHTMLSnippetStepsPA } from '../product-analytics/html-snippet'
import { StepDefinition } from '../steps'

export const getHTMLSnippetSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getHTMLSnippetStepsPA(ctx)

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

export const HTMLSnippetInstallation = createInstallation(getHTMLSnippetSteps)
