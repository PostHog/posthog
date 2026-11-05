import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getBubbleInstallSteps } from '../product-analytics/bubble'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getBubbleSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getBubbleInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const BubbleInstallation = createInstallation(getBubbleSteps)
