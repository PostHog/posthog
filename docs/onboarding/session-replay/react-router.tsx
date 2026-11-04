import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getReactRouterInstallSteps } from '../product-analytics/react-router'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getReactRouterInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
