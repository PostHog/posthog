import { useId } from 'react'

import { Field, FieldContent, FieldDescription, FieldLabel, Switch } from '@posthog/quill'

export function QuillSettingsSwitchRow({
    id,
    label,
    description,
    checked,
    onCheckedChange,
    loading,
    disabledReason,
    dataAttr,
}: {
    id?: string
    label: React.ReactNode
    description?: React.ReactNode
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    loading?: boolean
    disabledReason?: string | null
    dataAttr?: string
}): JSX.Element {
    const generatedId = useId()
    const switchId = id ?? generatedId

    return (
        <Field orientation="horizontal">
            <FieldContent>
                <FieldLabel htmlFor={switchId}>{label}</FieldLabel>
                {description && <FieldDescription>{description}</FieldDescription>}
            </FieldContent>
            <Switch
                id={switchId}
                checked={checked}
                onCheckedChange={(next) => onCheckedChange(next)}
                disabled={loading}
                disabledReason={disabledReason}
                data-attr={dataAttr}
            />
        </Field>
    )
}
