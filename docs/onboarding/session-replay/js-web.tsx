import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getJSWebSteps as getJSWebStepsPA } from '../product-analytics/js-web'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getJSWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getJSWebStepsPA, ctx)

export const JSWebInstallation = createInstallation(getJSWebSteps)
