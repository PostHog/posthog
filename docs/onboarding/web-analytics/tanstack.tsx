import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getTanStackInstallSteps } from '../product-analytics/tanstack'
import { StepDefinition } from '../steps'

export const getTanStackSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getTanStackInstallSteps(ctx),
        {
            title: 'Send events',
            content: <>{WebFinalSteps && <WebFinalSteps />}</>,
        },
    ]
}

export const TanStackInstallation = createInstallation(getTanStackSteps)
