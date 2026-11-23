import { Text } from '@posthog/quill'

import { KeyValidationResult, LLMProvider } from './llmProviderKeysLogic'

export function QuillKeyValidationStatus({
    result,
    isValidating,
    provider,
    providerLabel,
    suppressError,
}: {
    result: KeyValidationResult | null
    isValidating: boolean
    provider: LLMProvider
    providerLabel: string
    suppressError: boolean
}): JSX.Element | null {
    if (isValidating) {
        return (
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Validating key...
            </Text>
        )
    }

    const bullets = (
        <Text size="xs" variant="muted" render={<ul className="m-0 flex list-disc flex-col gap-0.5 pl-4" />}>
            <li>Your key will be encrypted and stored securely</li>
            <li>
                {provider === 'system_one'
                    ? 'Model usage is billed by your endpoint provider'
                    : `You pay ${providerLabel} directly for model usage`}
            </li>
            <li>Each evaluation counts as an AI observability event</li>
        </Text>
    )

    if (!result) {
        return bullets
    }

    if (result.state === 'ok') {
        return (
            <Text size="xs" className="text-success-foreground" render={<p className="m-0" />}>
                Key validated successfully
            </Text>
        )
    }

    return (
        <>
            {bullets}
            {!suppressError && (
                <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                    {result.error_message || 'Key validation failed'}
                </Text>
            )}
        </>
    )
}
