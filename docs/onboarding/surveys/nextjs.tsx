import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getNextJSSteps as getNextJSStepsPA } from '../product-analytics/nextjs'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getNextJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getNextJSStepsPA, ctx)

export const SurveysNextJSInstallation = createInstallation(getNextJSSteps)
