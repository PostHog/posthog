import { Field as KeaField } from 'kea-forms'
import { ReactNode } from 'react'

import { Checkbox, Field, FieldError, FieldLabel, Input } from '@posthog/quill'

interface QuillAlertEditorFormDetailsProps {
    enabled?: {
        checked: boolean
        dataAttr?: string
    }
    activity?: ReactNode
    nameDataAttr?: string
    nameError?: string
}

export function QuillAlertEditorFormDetails({
    enabled,
    activity,
    nameDataAttr = 'alertForm-name',
    nameError,
}: QuillAlertEditorFormDetailsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-4">
                <KeaField name="name" noStyle>
                    {({ id, value, onChange, error }) => {
                        const shownError = nameError ?? error

                        return (
                            <Field data-invalid={shownError ? true : undefined} className="min-w-0 flex-auto">
                                <FieldLabel htmlFor={id} className="sr-only">
                                    Alert name
                                </FieldLabel>
                                <Input
                                    id={id}
                                    value={value ?? ''}
                                    onChange={(event) => onChange(event.target.value)}
                                    placeholder="Alert name"
                                    aria-invalid={shownError ? true : undefined}
                                    data-attr={nameDataAttr}
                                />
                                {shownError ? <FieldError>{shownError}</FieldError> : null}
                            </Field>
                        )
                    }}
                </KeaField>
                {enabled ? (
                    <KeaField name="enabled" noStyle>
                        {({ id, onChange }) => (
                            <Field orientation="horizontal" className="w-fit">
                                <Checkbox
                                    id={id}
                                    checked={enabled.checked}
                                    onCheckedChange={(checked: boolean) => onChange(checked)}
                                    data-attr={enabled.dataAttr}
                                />
                                <FieldLabel htmlFor={id}>Enabled</FieldLabel>
                            </Field>
                        )}
                    </KeaField>
                ) : null}
            </div>
            {activity}
        </div>
    )
}
