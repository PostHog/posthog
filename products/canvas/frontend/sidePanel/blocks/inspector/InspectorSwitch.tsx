import { useId } from 'react'

import { Field, FieldContent, FieldDescription, FieldLabel, Switch } from '@posthog/quill'

/** An on or off inspector setting that applies at once, with its label on the left. */
export function InspectorSwitch({
    label,
    hint,
    checked,
    onChange,
}: {
    label: string
    hint?: string
    checked: boolean
    onChange: (checked: boolean) => void
}): JSX.Element {
    const id = useId()
    return (
        <Field orientation="horizontal">
            <FieldContent>
                <FieldLabel htmlFor={id}>{label}</FieldLabel>
                {hint ? <FieldDescription>{hint}</FieldDescription> : null}
            </FieldContent>
            <Switch id={id} checked={checked} onCheckedChange={onChange} size="sm" />
        </Field>
    )
}
