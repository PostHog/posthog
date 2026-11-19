import { Field as KeaField } from 'kea-forms'
import type { ReactElement, ReactNode } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel, Text, cn } from '@posthog/quill'

import type { CheckFormValues } from './dataQualityCheckEditorLogic'

export interface QuillCheckFormFieldControl {
    id: string
    value: any
    onChange: (value: any) => void
    invalid: boolean
}

export interface QuillCheckFormFieldProps {
    name: keyof CheckFormValues
    label: string
    optional?: boolean
    description?: ReactNode
    className?: string
    children: (control: QuillCheckFormFieldControl) => ReactElement
}

export function QuillCheckFormField({
    name,
    label,
    optional,
    description,
    className,
    children,
}: QuillCheckFormFieldProps): JSX.Element {
    return (
        <KeaField name={name} noStyle>
            {({ id, value, onChange, error }) => (
                <Field data-invalid={error ? true : undefined} className={cn('min-w-0', className)}>
                    <FieldLabel htmlFor={id}>
                        {label}
                        {optional && (
                            <Text size="xs" variant="muted" render={<span />}>
                                (optional)
                            </Text>
                        )}
                    </FieldLabel>
                    {children({ id, value, onChange, invalid: !!error })}
                    {description && <FieldDescription>{description}</FieldDescription>}
                    {error && <FieldError>{error}</FieldError>}
                </Field>
            )}
        </KeaField>
    )
}
