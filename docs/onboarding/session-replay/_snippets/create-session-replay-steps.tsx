import { OnboardingComponentsContext } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export function createSessionReplayStepsFromPA(
    getClientStepsPA: (ctx: OnboardingComponentsContext) => StepDefinition[],
    ctx: OnboardingComponentsContext
): StepDefinition[] {
    const { snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    return [
        ...getClientStepsPA(ctx),
        {
            title: 'Watch session recordings',
            badge: 'recommended',
            content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
        },
    ]
}
