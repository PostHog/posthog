import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getVueInstallSteps } from '../product-analytics/vue'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getVueSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getVueInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const VueInstallation = createInstallation(getVueSteps)
