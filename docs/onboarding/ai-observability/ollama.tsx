import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getOllamaSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Ollama',
        slug: 'ollama',
        baseUrl: 'http://localhost:11434/v1',
        apiKeyPlaceholder: 'ollama',
        defaultModel: 'llama3.2',
    })

export const OllamaInstallation = createInstallation(getOllamaSteps)
