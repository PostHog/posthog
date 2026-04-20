import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getBubbleSteps as getBubbleStepsPA } from '../product-analytics/bubble'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getBubbleSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getBubbleStepsPA, ctx)

export const BubbleInstallation = createInstallation(getBubbleSteps)
