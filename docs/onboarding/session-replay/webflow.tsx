import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getWebflowInstallSteps } from '../product-analytics/webflow'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getWebflowSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getWebflowInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const WebflowInstallation = createInstallation(getWebflowSteps)
