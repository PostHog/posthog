import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getWebSteps as getWebStepsPA } from '../product-analytics/web'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getWebStepsPA, ctx)

export const SurveysWebInstallation = createInstallation(getWebSteps)
