import { useId } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel, Input } from '@posthog/quill'

export function QuillFoundryEndpointField({
    value,
    onChange,
    errorMessage,
    optional,
    disabledReason = null,
}: {
    value: string
    onChange: (value: string) => void
    errorMessage: string | null
    optional: boolean
    disabledReason?: string | null
}): JSX.Element {
    const id = useId()

    return (
        <Field data-invalid={!!errorMessage || undefined}>
            <FieldLabel htmlFor={id}>
                {optional ? 'Microsoft Foundry endpoint (optional)' : 'Microsoft Foundry endpoint'}
            </FieldLabel>
            <Input
                id={id}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder="https://my-resource.services.ai.azure.com/"
                aria-invalid={!!errorMessage || undefined}
                disabled={!!disabledReason}
            />
            {errorMessage ? (
                <FieldError>{errorMessage}</FieldError>
            ) : disabledReason ? (
                <FieldDescription>{disabledReason}</FieldDescription>
            ) : (
                <FieldDescription>
                    {optional
                        ? 'Fill this in only if you run Claude on Microsoft Foundry. Leave it empty for a key from the Anthropic API.'
                        : 'The endpoint URL of your Microsoft Foundry resource'}
                </FieldDescription>
            )}
        </Field>
    )
}
