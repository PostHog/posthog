import { Field as KeaField } from 'kea-forms'
import { ReactElement, ReactNode } from 'react'

import { Field, FieldError, FieldLabel } from '@posthog/quill'

export interface QuillSettingFormFieldControl {
    id: string
    value: any
    onChange: (value: any) => void
    invalid: boolean
}

export function QuillSettingFormField({
    name,
    label,
    labelAction,
    children,
}: {
    name: string
    label: ReactNode
    /** Rendered beside the label, outside it, so a button here does not focus the input when clicked. */
    labelAction?: ReactNode
    children: (control: QuillSettingFormFieldControl) => ReactElement
}): JSX.Element {
    return (
        <KeaField name={name} noStyle>
            {({ id, value, onChange, error }) => (
                <Field data-invalid={error ? true : undefined}>
                    {labelAction ? (
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <FieldLabel htmlFor={id}>{label}</FieldLabel>
                            {labelAction}
                        </div>
                    ) : (
                        <FieldLabel htmlFor={id}>{label}</FieldLabel>
                    )}
                    {children({ id, value, onChange, invalid: !!error })}
                    {error && <FieldError>{error}</FieldError>}
                </Field>
            )}
        </KeaField>
    )
}
