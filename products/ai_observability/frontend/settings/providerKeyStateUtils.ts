import { LLMProvider, LLMProviderKey, LLMProviderKeyState, LLM_PROVIDER_LABELS } from './llmProviderKeysLogic'

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
