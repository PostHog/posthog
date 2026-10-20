import { useId } from 'react'

import { Field, FieldLabel, Switch, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

export interface QuillLabeledSwitchProps {
    checked: boolean
    onChange: (checked: boolean) => void
    label: React.ReactNode
    /** Extra help shown in a tooltip on the label. */
    tooltip?: React.ReactNode
    disabled?: boolean
    disabledReason?: React.ReactNode
    id?: string
    className?: string
    'data-attr'?: string
}

/** A quill switch with its label, for settings that apply at once (the quill form of `LemonSwitch` with a label). */
export function QuillLabeledSwitch({
    checked,
    onChange,
    label,
    tooltip,
    disabled,
    disabledReason,
    id,
    className,
    'data-attr': dataAttr,
}: QuillLabeledSwitchProps): JSX.Element {
    const generatedId = useId()
    const switchId = id ?? generatedId
    const isDisabled = disabled || !!disabledReason
    const help = disabledReason || tooltip

    const switchControl = (
        <Switch
            id={switchId}
            size="sm"
            checked={checked}
            onCheckedChange={(value: boolean) => onChange(value)}
            disabled={isDisabled}
            data-attr={dataAttr}
        />
    )

    return (
        <Field orientation="horizontal" className={cn('w-auto items-center gap-2', className)}>
            {help ? (
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex" />}>{switchControl}</TooltipTrigger>
                    <TooltipContent className="max-w-80">{help}</TooltipContent>
                </Tooltip>
            ) : (
                switchControl
            )}
            <FieldLabel htmlFor={switchId} className="font-normal">
                {label}
            </FieldLabel>
        </Field>
    )
}
