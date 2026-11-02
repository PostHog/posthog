import { useId } from 'react'

import { Checkbox, Field } from '@posthog/quill'

import type { ChartOptionSwitchProps } from './ChartOptionSwitch'
import { QuillChartOptionLabel } from './QuillChartOptionLabel'

export function QuillChartOptionCheckbox({
    label,
    info,
    checked,
    onChange,
    disabledReason,
    'data-attr': dataAttr,
}: ChartOptionSwitchProps): JSX.Element {
    const id = useId()

    return (
        <Field orientation="horizontal" className="min-h-6">
            <Checkbox
                id={id}
                checked={checked}
                onCheckedChange={(next: boolean) => onChange(next)}
                disabledReason={disabledReason || undefined}
                data-attr={dataAttr}
            />
            <QuillChartOptionLabel htmlFor={id} label={label} info={info} />
        </Field>
    )
}
