import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getHTMLSnippetSteps as getHTMLSnippetStepsPA } from '../product-analytics/html-snippet'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getHTMLSnippetSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getHTMLSnippetStepsPA, ctx)

export const HTMLSnippetInstallation = createInstallation(getHTMLSnippetSteps)
