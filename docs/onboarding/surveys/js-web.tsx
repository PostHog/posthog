import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getJSWebSteps as getJSWebStepsPA } from '../product-analytics/js-web'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getJSWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getJSWebStepsPA, ctx)

export const SurveysJSWebInstallation = createInstallation(getJSWebSteps)
