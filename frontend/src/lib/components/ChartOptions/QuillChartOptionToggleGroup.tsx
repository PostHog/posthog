import { useId } from 'react'

import { Field, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import type { ChartOptionToggleGroupProps } from './ChartOptionToggleGroup'
import { QuillChartOptionLabel } from './QuillChartOptionLabel'

export function QuillChartOptionToggleGroup<T extends string | number>({
    label,
    info,
    value,
    options,
    onChange,
    disabledReason,
    'data-attr': dataAttr,
}: ChartOptionToggleGroupProps<T>): JSX.Element {
    const id = useId()

    return (
        <Field data-attr={dataAttr}>
            {label && <QuillChartOptionLabel htmlFor={id} label={label} info={info} />}
            <ToggleGroup
                id={id}
                className="w-full"
                value={[String(value)]}
                onValueChange={(next: string[]) => {
                    const picked = options.find((option) => String(option.value) === next[0])
                    if (picked) {
                        onChange(picked.value)
                    }
                }}
            >
                {options.map((option) => (
                    <ToggleGroupItem
                        key={String(option.value)}
                        value={String(option.value)}
                        className="flex-1"
                        disabledReason={disabledReason || undefined}
                    >
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </Field>
    )
}
