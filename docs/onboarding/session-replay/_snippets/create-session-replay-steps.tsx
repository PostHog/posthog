import { OnboardingComponentsContext } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export function createSessionReplayStepsFromPA(
    getClientStepsPA: (ctx: OnboardingComponentsContext) => StepDefinition[],
    ctx: OnboardingComponentsContext
): StepDefinition[] {
    const { snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    const installationSteps = getClientStepsPA(ctx).filter(
        (step: StepDefinition) => step.title !== 'Send events'
    )

    return [
        ...installationSteps,
        {
            title: 'Watch session recordings',
            badge: 'recommended',
            content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
        },
    ]
}
