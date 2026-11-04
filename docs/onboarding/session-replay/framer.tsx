import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getFramerInstallSteps } from '../product-analytics/framer'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getFramerSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getFramerInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const FramerInstallation = createInstallation(getFramerSteps)
