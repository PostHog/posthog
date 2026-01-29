import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getAstroSteps as getAstroStepsPA } from '../product-analytics/astro'
import { StepDefinition } from '../steps'

export const getAstroSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getAstroStepsPA(ctx)

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

export const AstroInstallation = createInstallation(getAstroSteps)
