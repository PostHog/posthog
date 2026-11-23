import { useValues } from 'kea'
import { useId } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel, Input } from '@posthog/quill'

import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { QuillColorInput } from 'scenes/surveys/wizard/QuillColorInput'

export function QuillSurveyAppearanceInput({
    value,
    onChange,
    error,
    label,
    info,
    placeholder,
    disabledReason,
    inputType = 'text',
}: {
    value?: string
    onChange: (value: string) => void
    error?: string
    label: string
    info?: string
    placeholder?: string
    disabledReason?: string | null
    inputType?: 'text' | 'color'
}): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const id = useId()

    const disabled = !surveysStylingAvailable || !!disabledReason

    return (
        <Field data-invalid={error ? true : undefined}>
            <FieldLabel htmlFor={id}>{label}</FieldLabel>
            {inputType === 'color' ? (
                <QuillColorInput
                    id={id}
                    value={value}
                    onChange={onChange}
                    disabled={disabled}
                    disabledReason={disabledReason}
                />
            ) : (
                <Input
                    id={id}
                    value={value ?? ''}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder={placeholder}
                    disabled={disabled}
                    disabledReason={disabledReason}
                />
            )}
            {info && <FieldDescription>{info}</FieldDescription>}
            {error && <FieldError>{error}</FieldError>}
        </Field>
    )
}
