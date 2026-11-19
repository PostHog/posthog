import { useId } from 'react'

import { IconGear } from '@posthog/icons'
import { Button, Field, Switch } from '@posthog/quill'

import { QuillChartOptionLabel } from 'lib/components/ChartOptions/QuillChartOptionLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface QuillPathCleaningGlobalSwitchProps {
    checked: boolean
    onChange: (checked: boolean) => void
    info: string
    disabledReason?: string
    settingsUrl: string
    'data-attr'?: string
}

export function QuillPathCleaningGlobalSwitch({
    checked,
    onChange,
    info,
    disabledReason,
    settingsUrl,
    'data-attr': dataAttr,
}: QuillPathCleaningGlobalSwitchProps): JSX.Element {
    const id = useId()

    return (
        <Field orientation="horizontal" className="min-h-6">
            <Switch
                id={id}
                size="sm"
                checked={checked}
                onCheckedChange={(next: boolean) => onChange(next)}
                disabledReason={disabledReason}
                data-attr={dataAttr}
            />
            <div className="flex min-w-0 items-center gap-1">
                <QuillChartOptionLabel htmlFor={id} label="Apply global path URL cleaning" info={info} />
                <Button
                    size="icon"
                    aria-label="Path cleaning settings"
                    tooltip="Path cleaning settings"
                    render={<LinkPrimitive to={settingsUrl} />}
                >
                    <IconGear />
                </Button>
            </div>
        </Field>
    )
}
