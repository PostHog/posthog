import { useId } from 'react'

import { Field, Switch } from '@posthog/quill'

import type { ChartOptionSwitchProps } from './ChartOptionSwitch'
import { QuillChartOptionLabel } from './QuillChartOptionLabel'

export function QuillChartOptionSwitch({
    label,
    info,
    infoLink,
    checked,
    onChange,
    disabledReason,
    'data-attr': dataAttr,
}: ChartOptionSwitchProps): JSX.Element {
    const id = useId()

    return (
        <Field orientation="horizontal" className="min-h-6">
            <Switch
                id={id}
                size="sm"
                checked={checked}
                onCheckedChange={(next: boolean) => onChange(next)}
                disabledReason={disabledReason || undefined}
                data-attr={dataAttr}
            />
            <QuillChartOptionLabel htmlFor={id} label={label} info={info} infoLink={infoLink} />
        </Field>
    )
}
