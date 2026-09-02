import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getHeliconeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Helicone',
        slug: 'helicone',
        baseUrl: 'https://ai-gateway.helicone.ai/',
        apiKeyPlaceholder: '<helicone_api_key>',
        defaultModel: 'gpt-5-mini',
    })

export const HeliconeInstallation = createInstallation(getHeliconeSteps)
