import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getPerplexitySteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Perplexity',
        slug: 'perplexity',
        baseUrl: 'https://api.perplexity.ai',
        apiKeyPlaceholder: '<perplexity_api_key>',
        defaultModel: 'sonar',
    })

export const PerplexityInstallation = createInstallation(getPerplexitySteps)
