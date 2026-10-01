import { useId } from 'react'

import { Switch } from '@posthog/quill'

/** An on or off inspector setting, with its label on the left. */
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
        <div className="flex items-start justify-between gap-3">
            <label htmlFor={id} className="min-w-0 cursor-pointer">
                <span className="block text-xs text-foreground">{label}</span>
                {hint ? <span className="block text-xs leading-snug text-muted-foreground">{hint}</span> : null}
            </label>
            <Switch id={id} checked={checked} onCheckedChange={onChange} size="sm" />
        </div>
    )
}
