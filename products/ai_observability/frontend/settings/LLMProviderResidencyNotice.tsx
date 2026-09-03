import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { Region } from '~/types'

import { LLMProvider, LLM_PROVIDER_LABELS } from './llmProviderKeysLogic'

export function LLMProviderResidencyNotice({ provider }: { provider: LLMProvider }): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    // Azure OpenAI takes the endpoint from the key, so the customer picks the region there.
    // Every other provider goes to a fixed global endpoint.
    if (preflight?.region !== Region.EU || provider === 'azure_openai') {
        return null
    }

    return (
        <LemonBanner type="warning">
            Evaluations and playground requests with this key go to the global {LLM_PROVIDER_LABELS[provider]} endpoint.
            Your prompt and response content can be processed outside the EU, even though your PostHog data stays in the
            EU. To keep inference in the EU, add an Azure OpenAI key for an EU resource that uses a regional or EU data
            zone deployment. Global deployments can process requests in any Azure region.
        </LemonBanner>
    )
}
