import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getTogetherAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Together AI',
        slug: 'together-ai',
        baseUrl: 'https://api.together.xyz/v1',
        apiKeyPlaceholder: '<together_api_key>',
        defaultModel: 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
    })

export const TogetherAIInstallation = createInstallation(getTogetherAISteps)
