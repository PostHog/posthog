import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getAngularInstallSteps } from '../product-analytics/angular'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getAngularSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getAngularInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const AngularInstallation = createInstallation(getAngularSteps)
