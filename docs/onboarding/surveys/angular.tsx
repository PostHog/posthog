import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getAngularSteps as getAngularStepsPA } from '../product-analytics/angular'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getAngularSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getAngularStepsPA, ctx)

export const SurveysAngularInstallation = createInstallation(getAngularSteps)
