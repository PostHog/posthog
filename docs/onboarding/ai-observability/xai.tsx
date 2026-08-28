import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getXAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'xAI',
        slug: 'xai',
        baseUrl: 'https://api.x.ai/v1',
        apiKeyPlaceholder: '<xai_api_key>',
        defaultModel: 'grok-3',
    })

export const XAIInstallation = createInstallation(getXAISteps)
