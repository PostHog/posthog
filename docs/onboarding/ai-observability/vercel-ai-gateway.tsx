import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getVercelAIGatewaySteps = (ctx: OnboardingComponentsContext): StepDefinition[] =>
    getOpenAICompatibleSteps(ctx, {
        label: 'Vercel AI Gateway',
        slug: 'vercel-ai-gateway',
        baseUrl: 'https://ai-gateway.vercel.sh/v1',
        apiKeyPlaceholder: '<your_api_key>',
        defaultModel: 'gpt-5-mini',
    })

export const VercelAIGatewayInstallation = createInstallation(getVercelAIGatewaySteps)
