import { Field as KeaField } from 'kea-forms'
import type { ReactElement, ReactNode } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel, Text, cn } from '@posthog/quill'

import type { NewMetricFormValues } from '../dataCatalogNewMetricSceneLogic'

export interface QuillMetricFormFieldControl<K extends keyof NewMetricFormValues> {
    id: string
    value: NewMetricFormValues[K]
    onChange: (value: NewMetricFormValues[K]) => void
    invalid: boolean
}

export interface QuillMetricFormFieldProps<K extends keyof NewMetricFormValues> {
    name: K
    label?: string
    optional?: boolean
    description?: ReactNode
    className?: string
    children: (control: QuillMetricFormFieldControl<K>) => ReactElement
}

export function QuillMetricFormField<K extends keyof NewMetricFormValues>({
    name,
    label,
    optional,
    description,
    className,
    children,
}: QuillMetricFormFieldProps<K>): JSX.Element {
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
                    {children({ id, value: value as NewMetricFormValues[K], onChange, invalid: !!error })}
                    {description && <FieldDescription>{description}</FieldDescription>}
                    {error && <FieldError>{error}</FieldError>}
                </Field>
            )}
        </KeaField>
    )
}
