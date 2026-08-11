import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getGroqSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Groq',
        slug: 'groq',
        baseUrl: 'https://api.groq.com/openai/v1',
        apiKeyPlaceholder: '<groq_api_key>',
        defaultModel: 'llama-3.3-70b-versatile',
    })

export const GroqInstallation = createInstallation(getGroqSteps)
