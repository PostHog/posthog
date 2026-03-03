import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getFramerSteps as getFramerStepsPA } from '../product-analytics/framer'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getFramerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getFramerStepsPA, ctx)

export const SurveysFramerInstallation = createInstallation(getFramerSteps)
