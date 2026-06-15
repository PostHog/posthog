import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getNextJSClientSteps as getNextJSStepsPA } from '../product-analytics/nextjs'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getNextJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getNextJSStepsPA, ctx)

export const NextJSInstallation = createInstallation(getNextJSSteps)
