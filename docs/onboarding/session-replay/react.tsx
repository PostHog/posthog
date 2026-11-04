import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getReactInstallSteps } from '../product-analytics/react'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getReactSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getReactInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const ReactInstallation = createInstallation(getReactSteps)
