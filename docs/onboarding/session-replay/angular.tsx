import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getAngularSteps as getAngularStepsPA } from '../product-analytics/angular'
import { StepDefinition } from '../steps'
import { createSessionReplayStepsFromPA } from './_snippets/create-session-replay-steps'

export const getAngularSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    createSessionReplayStepsFromPA(getAngularStepsPA, ctx)

export const AngularInstallation = createInstallation(getAngularSteps)
