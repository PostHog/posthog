import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getAstroSteps as getAstroStepsPA } from '../product-analytics/astro'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getAstroSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getAstroStepsPA, ctx)

export const SurveysAstroInstallation = createInstallation(getAstroSteps)
