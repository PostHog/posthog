import { OnboardingComponentsContext } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export const sessionReplayFinalStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const SessionReplayFinalSteps = ctx.snippets?.SessionReplayFinalSteps

    return {
        title: 'Watch session recordings',
        badge: 'recommended',
        content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
    }
}
