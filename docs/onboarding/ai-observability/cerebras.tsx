import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getCerebrasSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Cerebras',
        slug: 'cerebras',
        baseUrl: 'https://api.cerebras.ai/v1',
        apiKeyPlaceholder: '<cerebras_api_key>',
        defaultModel: 'llama-3.3-70b',
    })

export const CerebrasInstallation = createInstallation(getCerebrasSteps)
