import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getWebflowSteps as getWebflowStepsPA } from '../product-analytics/webflow'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getWebflowSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getWebflowStepsPA, ctx)

export const SurveysWebflowInstallation = createInstallation(getWebflowSteps)
