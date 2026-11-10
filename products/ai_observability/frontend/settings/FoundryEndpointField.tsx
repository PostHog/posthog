import { LemonInput } from '@posthog/lemon-ui'

export function FoundryEndpointField({
    value,
    onChange,
    errorMessage,
    optional,
}: {
    value: string
    onChange: (value: string) => void
    errorMessage: string | null
    optional: boolean
}): JSX.Element {
    return (
        <div>
            <label className="text-sm font-medium">
                {optional ? 'Microsoft Foundry endpoint (optional)' : 'Microsoft Foundry endpoint'}
            </label>
            <LemonInput
                value={value}
                onChange={onChange}
                placeholder="https://my-resource.services.ai.azure.com/"
                className="mt-1"
                fullWidth
                status={errorMessage ? 'danger' : undefined}
            />
            {errorMessage ? (
                <p className="text-xs text-danger mt-1">{errorMessage}</p>
            ) : (
                <p className="text-xs text-muted mt-1">
                    {optional
                        ? 'Fill this in only if you run Claude on Microsoft Foundry. Leave it empty for a key from the Anthropic API.'
                        : 'The endpoint URL of your Microsoft Foundry resource'}
                </p>
            )}
        </div>
    )
}
