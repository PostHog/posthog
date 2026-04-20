import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactRouterSteps as getReactRouterStepsPA } from '../product-analytics/react-router'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getReactRouterStepsPA, ctx)

export const SurveysReactRouterInstallation = createInstallation(getReactRouterSteps)
