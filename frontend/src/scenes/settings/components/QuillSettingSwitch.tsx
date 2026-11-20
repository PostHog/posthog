import { ReactNode, useId } from 'react'

import { IconInfo } from '@posthog/icons'
import { Button, Field, FieldLabel, Switch, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillSettingSwitch({
    id,
    label,
    help,
    checked,
    onCheckedChange,
    disabled,
    disabledReason,
    dataAttr,
}: {
    id?: string
    label: ReactNode
    /** Shown in a tooltip on an info button after the label. */
    help?: string
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    disabled?: boolean
    disabledReason?: string | null
    dataAttr?: string
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
                data-attr={dataAttr}
            />
            <FieldLabel htmlFor={switchId}>{label}</FieldLabel>
            {help && (
                <Tooltip>
                    <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="More information" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">{help}</TooltipContent>
                </Tooltip>
            )}
        </Field>
    )
}
