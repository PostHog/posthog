import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getAstroInstallSteps } from '../product-analytics/astro'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getAstroSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getAstroInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const AstroInstallation = createInstallation(getAstroSteps)
