import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getHuggingFaceSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Hugging Face',
        slug: 'hugging-face',
        baseUrl: 'https://router.huggingface.co/v1/',
        apiKeyPlaceholder: '<huggingface_api_key>',
        defaultModel: 'meta-llama/Llama-3.3-70B-Instruct',
    })

export const HuggingFaceInstallation = createInstallation(getHuggingFaceSteps)
