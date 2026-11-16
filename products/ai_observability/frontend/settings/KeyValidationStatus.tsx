import { KeyValidationResult, LLMProvider, LLM_PROVIDER_LABELS } from './llmProviderKeysLogic'

export function KeyValidationStatus({
    result,
    isValidating,
    provider,
    suppressError = false,
    usesFoundry = false,
}: {
    result: KeyValidationResult | null
    isValidating: boolean
    provider: LLMProvider
    suppressError?: boolean
    usesFoundry?: boolean
}): JSX.Element | null {
    if (isValidating) {
        return <p className="text-xs text-muted mt-1">Validating key...</p>
    }

    const providerLabel =
        provider === 'openai_compatible' ? 'your provider' : usesFoundry ? 'Microsoft' : LLM_PROVIDER_LABELS[provider]
    const bullets = (
        <ul className="text-xs text-muted mt-1 list-disc pl-4 space-y-0.5">
            <li>Your key will be encrypted and stored securely</li>
            <li>
                {provider === 'system_one'
                    ? 'Model usage is billed by your endpoint provider'
                    : `You pay ${providerLabel} directly for model usage`}
            </li>
            <li>Each evaluation counts as an AI observability event</li>
        </ul>
    )

    if (!result) {
        return bullets
    }

    if (result.state === 'ok') {
        return <p className="text-xs text-success mt-1">Key validated successfully</p>
    }

    return (
        <>
            {bullets}
            {!suppressError && (
                <p className="text-xs text-danger mt-1">{result.error_message || 'Key validation failed'}</p>
            )}
        </>
    )
}
