import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

import { getAngularInstallSteps } from '../product-analytics/angular'
import { StepDefinition } from '../steps'
import { sessionReplayFinalStep } from './_snippets/session-replay-final-step'

export const getAngularSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getAngularInstallSteps(ctx),
    sessionReplayFinalStep(ctx),
]

export const AngularInstallation = createInstallation(getAngularSteps)
