import { useId } from 'react'

import { Button, Field, FieldLabel, Input } from '@posthog/quill'

export function QuillWidgetTextField({
    label,
    value,
    placeholder,
    saveDisabledReason,
    onChange,
    onSave,
}: {
    label: string
    value: string
    placeholder: string
    saveDisabledReason: string | undefined
    onChange: (value: string) => void
    onSave: () => void
}): JSX.Element {
    const id = useId()

    return (
        <Field>
            <FieldLabel htmlFor={id}>{label}</FieldLabel>
            <div className="flex flex-wrap gap-2">
                <Input
                    id={id}
                    className="min-w-60 flex-1"
                    value={value}
                    placeholder={placeholder}
                    onChange={(event) => onChange(event.target.value)}
                />
                <Button variant="primary" onClick={onSave} disabledReason={saveDisabledReason}>
                    Save
                </Button>
            </div>
        </Field>
    )
}
