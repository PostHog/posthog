import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getReactRouterInstallSteps } from '../product-analytics/react-router'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getReactRouterInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
