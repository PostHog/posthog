import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getDeepSeekSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'DeepSeek',
        slug: 'deepseek',
        baseUrl: 'https://api.deepseek.com',
        apiKeyPlaceholder: '<deepseek_api_key>',
        defaultModel: 'deepseek-chat',
    })

export const DeepSeekInstallation = createInstallation(getDeepSeekSteps)
