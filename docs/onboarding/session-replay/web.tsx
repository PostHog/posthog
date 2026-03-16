import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getWebSteps as getWebStepsPA } from '../product-analytics/web'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getWebStepsPA, ctx)

export const WebInstallation = createInstallation(getWebSteps)
