import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getHTMLSnippetSteps as getHTMLSnippetStepsPA } from '../product-analytics/html-snippet'
import { StepDefinition } from '../steps'
import { createSurveysStepsFromPA } from './_snippets/create-surveys-steps'

export const getHTMLSnippetSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSurveysStepsFromPA(getHTMLSnippetStepsPA, ctx)

export const SurveysHTMLSnippetInstallation = createInstallation(getHTMLSnippetSteps)
