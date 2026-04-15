import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactRouterSteps as getReactRouterStepsPA } from '../product-analytics/react-router'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getReactRouterStepsPA, ctx)

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
