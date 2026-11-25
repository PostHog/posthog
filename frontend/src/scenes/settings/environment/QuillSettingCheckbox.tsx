import { useId } from 'react'

import { Checkbox, Field, FieldLabel } from '@posthog/quill'

export function QuillSettingCheckbox({
    label,
    checked,
    onCheckedChange,
    disabled,
    disabledReason,
}: {
    label: string
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    disabled?: boolean
    disabledReason?: string | null
}): JSX.Element {
    const checkboxId = useId()

    return (
        <Field orientation="horizontal" className="w-fit">
            <Checkbox
                id={checkboxId}
                checked={checked}
                onCheckedChange={onCheckedChange}
                disabled={disabled}
                disabledReason={disabledReason}
            />
            <FieldLabel htmlFor={checkboxId}>{label}</FieldLabel>
        </Field>
    )
}
