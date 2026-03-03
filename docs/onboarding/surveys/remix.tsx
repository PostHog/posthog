import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getRemixSteps as getRemixStepsPA } from '../product-analytics/remix'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getRemixSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getRemixStepsPA, ctx)

export const SurveysRemixInstallation = createInstallation(getRemixSteps)
