import { Form, Field as KeaField } from 'kea-forms'

import {
    Button,
    Field,
    FieldError,
    FieldLabel,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
    Textarea,
} from '@posthog/quill'

import { CORE_MEMORY_MAX_CHARACTERS, maxSettingsLogic } from './maxSettingsLogic'

const CORE_MEMORY_TEXTAREA_ID = 'product-description-textarea'

export function QuillMaxMemorySettings({
    loading,
    loadError,
    overLimit,
    updating,
    placeholder,
    restrictedReason,
    saveDisabledReason,
    onRetry,
    onTrim,
}: {
    loading: boolean
    loadError: string | null
    overLimit: boolean
    updating: boolean
    placeholder: string
    restrictedReason: string | null
    saveDisabledReason: string | null
    onRetry: () => void
    onTrim: () => void
}): JSX.Element {
    return (
        <Form
            logic={maxSettingsLogic}
            formKey="coreMemoryForm"
            enableFormOnSubmit
            className="flex flex-col items-start gap-4 w-full"
        >
            <Text size="xs" variant="muted" render={<p className="m-0 max-w-160" />}>
                When memory exceeds 5,000 characters, only the first and last 2,500 characters are visible to PostHog
                AI. The maximum memory size is {CORE_MEMORY_MAX_CHARACTERS.toLocaleString()} characters.
            </Text>
            {loading ? (
                <div className="flex flex-col gap-2 w-full">
                    <Skeleton className="h-6 w-32" />
                    <Skeleton className="h-16" />
                </div>
            ) : loadError ? (
                <Item tone="destructive" size="sm" className="max-w-160">
                    <ItemContent>
                        <ItemDescription>
                            Could not load PostHog AI's memory. This does not mean your memory is empty. Your saved
                            memory is safe. {loadError}
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={onRetry}>
                            Retry
                        </Button>
                    </ItemActions>
                </Item>
            ) : (
                <>
                    {overLimit && (
                        <Item tone="warning" size="sm" className="max-w-160">
                            <ItemContent>
                                <ItemDescription>
                                    This memory is over the {CORE_MEMORY_MAX_CHARACTERS.toLocaleString()}-character
                                    limit and can't be saved until it fits. Trimming keeps the first{' '}
                                    {CORE_MEMORY_MAX_CHARACTERS.toLocaleString()} characters.
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <Button variant="outline" onClick={onTrim} disabledReason={restrictedReason}>
                                    Trim to fit
                                </Button>
                            </ItemActions>
                        </Item>
                    )}
                    <KeaField name="text" noStyle>
                        {({ value, onChange, error }) => (
                            <Field data-invalid={error ? true : undefined} className="w-full">
                                <FieldLabel htmlFor={CORE_MEMORY_TEXTAREA_ID}>PostHog AI's memory</FieldLabel>
                                <Textarea
                                    id={CORE_MEMORY_TEXTAREA_ID}
                                    value={value ?? ''}
                                    onChange={(event) => onChange(event.target.value)}
                                    placeholder={placeholder}
                                    maxLength={CORE_MEMORY_MAX_CHARACTERS}
                                    rows={5}
                                    disabledReason={restrictedReason}
                                    aria-invalid={error ? true : undefined}
                                />
                                {error && <FieldError>{error}</FieldError>}
                            </Field>
                        )}
                    </KeaField>
                </>
            )}
            <Button type="submit" variant="primary" disabledReason={saveDisabledReason} loading={updating}>
                Save memory
            </Button>
        </Form>
    )
}
