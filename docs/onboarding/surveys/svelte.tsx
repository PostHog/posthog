import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getSvelteSteps as getSvelteStepsPA } from '../product-analytics/svelte'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getSvelteSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getSvelteStepsPA, ctx)

export const SurveysSvelteInstallation = createInstallation(getSvelteSteps)
