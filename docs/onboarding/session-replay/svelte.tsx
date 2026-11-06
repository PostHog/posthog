import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getSvelteClientSteps } from '../product-analytics/svelte'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getSvelteSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getSvelteClientSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const SvelteInstallation = createInstallation(getSvelteSteps)
