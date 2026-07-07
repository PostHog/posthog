import { LemonCheckbox, LemonSwitch } from '@posthog/lemon-ui'

/** How an insight display toggle renders: `checkbox` in the Options menu, `switch` in the editor panel. */
export type InsightToggleVariant = 'checkbox' | 'switch'

export interface InsightDisplayToggleProps {
    label: string
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string
    variant?: InsightToggleVariant
}

export function InsightDisplayToggle({
    label,
    checked,
    onChange,
    disabledReason,
    variant = 'checkbox',
}: InsightDisplayToggleProps): JSX.Element {
    if (variant === 'switch') {
        // No own padding — the editor panel's flex gap provides the spacing between rows
        return (
            <LemonSwitch
                label={label}
                fullWidth
                checked={checked}
                onChange={onChange}
                disabledReason={disabledReason}
            />
        )
    }
    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={onChange}
            checked={checked}
            disabledReason={disabledReason}
            label={<span className="font-normal">{label}</span>}
            size="small"
        />
    )
}
