import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getGoogleTagManagerInstallSteps } from '../product-analytics/google-tag-manager'
import { StepDefinition } from '../steps'

export const getGoogleTagManagerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getGoogleTagManagerInstallSteps(ctx),
        {
            title: 'Send events',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const GoogleTagManagerInstallation = createInstallation(getGoogleTagManagerSteps)
