import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getBubbleSteps as getBubbleStepsPA } from '../product-analytics/bubble'
import { StepDefinition } from '../steps'

export const getBubbleSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getBubbleStepsPA(ctx)

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

export const BubbleInstallation = createInstallation(getBubbleSteps)
