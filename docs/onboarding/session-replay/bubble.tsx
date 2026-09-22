import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getBubbleInstallSteps } from '../product-analytics/bubble'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getBubbleSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getBubbleInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const BubbleInstallation = createInstallation(getBubbleSteps)
