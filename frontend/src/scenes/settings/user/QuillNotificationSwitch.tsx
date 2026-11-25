import { useId } from 'react'

import { Badge, Field, FieldContent, FieldDescription, FieldLabel, Switch } from '@posthog/quill'

export function QuillNotificationSwitch({
    label,
    description,
    checked,
    onCheckedChange,
    disabledReason,
    lockedByAdmin = false,
    dataAttr,
}: {
    label: string
    description: string
    checked: boolean
    onCheckedChange?: (checked: boolean) => void
    disabledReason?: string
    lockedByAdmin?: boolean
    dataAttr: string
}): JSX.Element {
    const switchId = useId()

    return (
        <Field orientation="horizontal">
            <Switch
                id={switchId}
                checked={checked}
                onCheckedChange={onCheckedChange}
                disabledReason={disabledReason}
                data-attr={dataAttr}
            />
            <FieldContent>
                <FieldLabel htmlFor={switchId}>
                    <span className="flex flex-wrap items-center gap-2">
                        {label}
                        {lockedByAdmin && <Badge variant="info">Set by your admin</Badge>}
                    </span>
                </FieldLabel>
                <FieldDescription>{description}</FieldDescription>
            </FieldContent>
        </Field>
    )
}
