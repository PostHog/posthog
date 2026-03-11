import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getBubbleSteps as getBubbleStepsPA } from '../product-analytics/bubble'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getBubbleSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getBubbleStepsPA, ctx)

export const SurveysBubbleInstallation = createInstallation(getBubbleSteps)
