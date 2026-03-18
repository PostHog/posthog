import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getSvelteClientSteps as getSvelteStepsPA } from '../product-analytics/svelte'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getSvelteSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getSvelteStepsPA, ctx)

export const SvelteInstallation = createInstallation(getSvelteSteps)
