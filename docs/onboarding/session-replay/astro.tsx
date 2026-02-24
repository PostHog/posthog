import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getAstroSteps as getAstroStepsPA } from '../product-analytics/astro'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getAstroSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getAstroStepsPA, ctx)

export const AstroInstallation = createInstallation(getAstroSteps)
