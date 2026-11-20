import { Field, FieldError, FieldGroup, FieldLabel, Input, Text } from '@posthog/quill'

export function QuillSystemOneConnectionFields({
    baseUrl,
    model,
    loading,
    baseUrlError,
    modelError,
    onBaseUrlChange,
    onModelChange,
}: {
    baseUrl: string
    model: string
    loading: boolean
    baseUrlError: string | null
    modelError: string | null
    onBaseUrlChange: (value: string) => void
    onModelChange: (value: string) => void
}): JSX.Element {
    return (
        <FieldGroup>
            <Field data-invalid={!!baseUrlError || undefined}>
                <FieldLabel htmlFor="system-one-base-url">Base URL</FieldLabel>
                <Input
                    id="system-one-base-url"
                    value={baseUrl}
                    onChange={(event) => onBaseUrlChange(event.target.value)}
                    disabled={loading}
                    placeholder="https://decisions.example.com/v1"
                    data-attr="system-one-base-url"
                    aria-invalid={!!baseUrlError || undefined}
                />
                {baseUrlError && <FieldError>{baseUrlError}</FieldError>}
            </Field>
            <Field data-invalid={!!modelError || undefined}>
                <FieldLabel htmlFor="system-one-model">Model ID</FieldLabel>
                <Input
                    id="system-one-model"
                    value={model}
                    onChange={(event) => onModelChange(event.target.value)}
                    disabled={loading}
                    placeholder="Your model ID"
                    data-attr="system-one-model"
                    aria-invalid={!!modelError || undefined}
                />
                {modelError && <FieldError>{modelError}</FieldError>}
            </Field>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Enter the public HTTPS base URL, ending before /systemone. Validation sends a short synthetic example to
                the selected model.
            </Text>
        </FieldGroup>
    )
}
