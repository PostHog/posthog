import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getCohereSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Cohere',
        slug: 'cohere',
        baseUrl: 'https://api.cohere.ai/compatibility/v1',
        apiKeyPlaceholder: '<cohere_api_key>',
        defaultModel: 'command-a-03-2025',
    })

export const CohereInstallation = createInstallation(getCohereSteps)
