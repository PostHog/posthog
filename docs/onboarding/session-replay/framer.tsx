import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getFramerSteps as getFramerStepsPA } from '../product-analytics/framer'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getFramerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getFramerStepsPA, ctx)

export const FramerInstallation = createInstallation(getFramerSteps)
