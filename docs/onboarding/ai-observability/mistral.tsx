import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getMistralSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Mistral',
        slug: 'mistral',
        baseUrl: 'https://api.mistral.ai/v1',
        apiKeyPlaceholder: '<mistral_api_key>',
        defaultModel: 'mistral-large-latest',
    })

export const MistralInstallation = createInstallation(getMistralSteps)
