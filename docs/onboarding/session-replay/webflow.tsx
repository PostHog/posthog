import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getWebflowSteps as getWebflowStepsPA } from '../product-analytics/webflow'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getWebflowSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getWebflowStepsPA, ctx)

export const WebflowInstallation = createInstallation(getWebflowSteps)
