import { OnboardingComponentsContext } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export function createSessionReplayStepsFromPA(
    getStepsPA: (ctx: OnboardingComponentsContext) => StepDefinition[],
    ctx: OnboardingComponentsContext
): StepDefinition[] {
    const { snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    return getStepsPA(ctx).map((step) => {
        if (step.title === 'Send events') {
            return {
                ...step,
                title: 'Create a recording',
                content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
            }
        }
        return step
    })
}
