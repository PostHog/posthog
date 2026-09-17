import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getNextJSClientSteps } from '../product-analytics/nextjs'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getNextJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getNextJSClientSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const NextJSInstallation = createInstallation(getNextJSSteps)
