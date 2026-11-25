import { LogicWrapper } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'
import { ReactNode } from 'react'

import { Button, Field, FieldError, FieldLabel, Input, Text } from '@posthog/quill'

import { QuillUrlPatternHint } from './QuillUrlPatternHint'

export function QuillUrlConfigForm({
    onCancel,
    isSubmitting,
    logic,
    logicProps,
    formKey,
    validationWarning,
    aiRegexHelper,
}: {
    onCancel: () => void
    isSubmitting: boolean
    logic: LogicWrapper
    logicProps: Record<string, any>
    formKey: string
    validationWarning: string | null
    aiRegexHelper?: ReactNode
}): JSX.Element {
    return (
        <Form
            logic={logic}
            props={logicProps}
            formKey={formKey}
            enableFormOnSubmit
            className="flex w-full flex-col gap-3 rounded-md border border-border p-3"
        >
            <QuillUrlPatternHint />
            <KeaField name="url" noStyle>
                {({ id, value, onChange, error }) => (
                    <Field data-invalid={error ? true : undefined}>
                        <FieldLabel htmlFor={id}>Matching regex:</FieldLabel>
                        <Input
                            id={id}
                            value={value ?? ''}
                            onChange={(event) => onChange(event.target.value)}
                            autoFocus
                            placeholder="e.g., https://example.com/checkout.*, ^https://example.com/page$"
                            data-attr="url-input"
                        />
                        {error && <FieldError>{error}</FieldError>}
                    </Field>
                )}
            </KeaField>
            {validationWarning && (
                <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                    {validationWarning}
                </Text>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>{aiRegexHelper}</div>
                <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={onCancel}>
                        Cancel
                    </Button>
                    <Button
                        type="submit"
                        variant="primary"
                        disabledReason={isSubmitting ? `Saving url in progress` : undefined}
                        data-attr="url-save"
                    >
                        Save
                    </Button>
                </div>
            </div>
        </Form>
    )
}
