import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getWebflowSteps as getWebflowStepsPA } from '../product-analytics/webflow'
import { StepDefinition } from '../steps'

export const getWebflowSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getWebflowStepsPA(ctx)

    // Replace the "Send events" step with session replay specific content
    const sessionReplaySteps = paSteps.map((step) => {
        if (step.title === 'Send events') {
            return {
                ...step,
                title: 'Create a recording',
                content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
            }
        }
        return step
    })

    return sessionReplaySteps
}

export const WebflowInstallation = createInstallation(getWebflowSteps)
