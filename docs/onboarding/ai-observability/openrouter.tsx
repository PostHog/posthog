import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getOpenRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'OpenRouter',
        slug: 'openrouter',
        baseUrl: 'https://openrouter.ai/api/v1',
        apiKeyPlaceholder: '<openrouter_api_key>',
        defaultModel: 'gpt-5-mini',
    })

export const OpenRouterInstallation = createInstallation(getOpenRouterSteps)
