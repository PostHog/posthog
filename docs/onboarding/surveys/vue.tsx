import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getVueSteps as getVueStepsPA } from '../product-analytics/vue'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getVueSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getVueStepsPA, ctx)

export const SurveysVueInstallation = createInstallation(getVueSteps)
