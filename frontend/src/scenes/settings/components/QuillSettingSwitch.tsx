import { useId } from 'react'

import { Field, FieldLabel, Switch } from '@posthog/quill'

export function QuillSettingSwitch({
    id,
    label,
    checked,
    onCheckedChange,
    disabled,
    disabledReason,
}: {
    id?: string
    label: string
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    disabled?: boolean
    disabledReason?: string | null
}): JSX.Element {
    const generatedId = useId()
    const switchId = id ?? generatedId

    return (
        <Field orientation="horizontal" className="w-fit">
            <Switch
                id={switchId}
                checked={checked}
                onCheckedChange={onCheckedChange}
                disabled={disabled}
                disabledReason={disabledReason}
            />
            <FieldLabel htmlFor={switchId}>{label}</FieldLabel>
        </Field>
    )
}
