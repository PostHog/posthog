import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getFireworksAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Fireworks AI',
        slug: 'fireworks-ai',
        baseUrl: 'https://api.fireworks.ai/inference/v1',
        apiKeyPlaceholder: '<fireworks_api_key>',
        defaultModel: 'accounts/fireworks/models/llama-v3p3-70b-instruct',
    })

export const FireworksAIInstallation = createInstallation(getFireworksAISteps)
