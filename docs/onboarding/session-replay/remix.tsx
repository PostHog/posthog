import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getRemixSteps as getRemixStepsPA } from '../product-analytics/remix'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getRemixSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getRemixStepsPA, ctx)

export const RemixInstallation = createInstallation(getRemixSteps)
