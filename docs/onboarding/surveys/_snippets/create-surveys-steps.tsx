import { OnboardingComponentsContext } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export function createSurveysStepsFromPA(
    getClientStepsPA: (ctx: OnboardingComponentsContext) => StepDefinition[],
    ctx: OnboardingComponentsContext
): StepDefinition[] {
    const { snippets } = ctx
    const SurveysFinalSteps = snippets?.SurveysFinalSteps

    const installationSteps = getClientStepsPA(ctx)

    return [
        ...installationSteps,
        {
            title: 'Next steps',
            badge: 'recommended',
            content: <>{SurveysFinalSteps && <SurveysFinalSteps />}</>,
        },
    ]
}
