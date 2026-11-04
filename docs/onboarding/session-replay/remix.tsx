import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getRemixInstallSteps } from '../product-analytics/remix'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getRemixSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getRemixInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const RemixInstallation = createInstallation(getRemixSteps)
