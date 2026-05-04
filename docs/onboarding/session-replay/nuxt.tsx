import {
    OnboardingComponentsContext,
    createInstallation,
} from 'products/growth/frontend/onboarding/OnboardingDocsContentWrapper'

import { getNuxtClientSteps as getNuxtStepsPA } from '../product-analytics/nuxt'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getNuxtSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getNuxtStepsPA, ctx)

export const NuxtInstallation = createInstallation(getNuxtSteps)
