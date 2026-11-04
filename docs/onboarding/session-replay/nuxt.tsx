import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getNuxtClientSteps } from '../product-analytics/nuxt'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getNuxtSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getNuxtClientSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const NuxtInstallation = createInstallation(getNuxtSteps)
