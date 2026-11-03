import { Field as KeaField } from 'kea-forms'
import type { ReactElement, ReactNode } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel, Text, cn } from '@posthog/quill'

import type { NewMetricFormValues } from '../dataCatalogNewMetricSceneLogic'

export interface QuillMetricFormFieldControl {
    id: string
    value: any
    onChange: (value: any) => void
    invalid: boolean
}

export interface QuillMetricFormFieldProps {
    name: keyof NewMetricFormValues
    label?: string
    optional?: boolean
    description?: ReactNode
    className?: string
    children: (control: QuillMetricFormFieldControl) => ReactElement
}

export function QuillMetricFormField({
    name,
    label,
    optional,
    description,
    className,
    children,
}: QuillMetricFormFieldProps): JSX.Element {
    return (
        <KeaField name={name} noStyle>
            {({ id, value, onChange, error }) => (
                <Field data-invalid={error ? true : undefined} className={cn('min-w-0', className)}>
                    {label && (
                        <FieldLabel htmlFor={id}>
                            {label}
                            {optional && (
                                <Text size="xs" variant="muted" render={<span />}>
                                    (optional)
                                </Text>
                            )}
                        </FieldLabel>
                    )}
                    {children({ id, value, onChange, invalid: !!error })}
                    {description && <FieldDescription>{description}</FieldDescription>}
                    {error && <FieldError>{error}</FieldError>}
                </Field>
            )}
        </KeaField>
    )
}
