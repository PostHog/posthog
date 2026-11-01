import {
    KeyValidationResult,
    LLMProvider,
    LLMProviderKey,
    LLMProviderKeyState,
    LLM_PROVIDER_LABELS,
} from './llmProviderKeysLogic'

const UNHEALTHY_PROVIDER_KEY_STATES = new Set<LLMProviderKeyState>(['unknown', 'invalid', 'error'])

export function isUnhealthyProviderKeyState(state: LLMProviderKeyState): boolean {
    return UNHEALTHY_PROVIDER_KEY_STATES.has(state)
}

export function getUnhealthyProviderKey(
    providerKeys: LLMProviderKey[],
    providerKeyId?: string | null
): LLMProviderKey | null {
    if (!providerKeyId) {
        return null
    }

    const providerKey = providerKeys.find((key) => key.id === providerKeyId)
    if (!providerKey || !isUnhealthyProviderKeyState(providerKey.state)) {
        return null
    }

    return providerKey
}

export function providerKeyStateLabel(state: LLMProviderKeyState): string {
    switch (state) {
        case 'invalid':
            return 'Invalid'
        case 'error':
            return 'Error'
        case 'ok':
            return 'Valid'
        case 'unknown':
            return 'Unknown'
    }
}

export function providerKeyStateIssueDescription(state: LLMProviderKeyState): string {
    switch (state) {
        case 'invalid':
            return 'is invalid'
        case 'error':
            return 'had an error'
        case 'ok':
            return 'is valid'
        case 'unknown':
            return 'has unknown status'
    }
}

export function providerKeyStateSuffix(state: LLMProviderKeyState): string {
    if (state === 'invalid') {
        return ' (Invalid)'
    }
    if (state === 'error') {
        return ' (Error)'
    }
    if (state === 'unknown') {
        return ' (Unknown status)'
    }
    return ''
}

export function providerLabel(provider: LLMProvider): string {
    return LLM_PROVIDER_LABELS[provider]
}

export function getKeyPlaceholder(provider: LLMProvider, usesFoundry = false): string {
    switch (provider) {
        case 'openai':
            return 'sk-...'
        case 'anthropic':
            return usesFoundry ? 'Enter your Microsoft Foundry API key' : 'sk-ant-...'
        case 'gemini':
            return 'Enter your Gemini API key'
        case 'together_ai':
            return 'Enter your Together AI API key'
        case 'openrouter':
            return 'Enter your OpenRouter API key'
        case 'fireworks':
            return 'Enter your Fireworks API key'
        case 'azure_openai':
            return 'Enter your Azure OpenAI API key'
        case 'minimax':
            return 'Enter your MiniMax API key'
        case 'system_one':
            return "Enter your endpoint's bearer token"
        case 'openai_compatible':
            return 'Enter your API key'
    }
}

// Azure and OpenAI-compatible validation errors can originate from either the endpoint or the
// API key. The backend tells us which via `error_field`; map it to which input the key form
// highlights.
export function endpointErrorFieldFromResult(
    result: KeyValidationResult | null | undefined
): 'endpoint' | 'key' | null {
    if (!result || result.state === 'ok') {
        return null
    }
    return result.error_field === 'azure_endpoint' || result.error_field === 'base_url' ? 'endpoint' : 'key'
}
