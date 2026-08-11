import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getDedalusSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Dedalus Labs',
        slug: 'dedalus',
        baseUrl: 'https://api.dedaluslabs.ai/v1',
        apiKeyPlaceholder: '<dedalus_api_key>',
        defaultModel: 'openai/gpt-5-mini',
    })

export const DedalusInstallation = createInstallation(getDedalusSteps)
