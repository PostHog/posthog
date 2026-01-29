import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getFramerSteps as getFramerStepsPA } from '../product-analytics/framer'
import { StepDefinition } from '../steps'

export const getFramerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getFramerStepsPA(ctx)

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

export const FramerInstallation = createInstallation(getFramerSteps)
