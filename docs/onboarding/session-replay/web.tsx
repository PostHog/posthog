import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getWebInstallSteps } from '../product-analytics/web'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getWebInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const WebInstallation = createInstallation(getWebSteps)
