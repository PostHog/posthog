import { useId } from 'react'

import { Button, Field, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import type { ChartOptionSelectProps } from './ChartOptionSelect'
import { QuillChartOptionLabel } from './QuillChartOptionLabel'

export function QuillChartOptionSelect<T extends string | number>({
    label,
    info,
    value,
    options,
    onChange,
    disabledReason,
    'data-attr': dataAttr,
}: ChartOptionSelectProps<T>): JSX.Element {
    const id = useId()

    return (
        <Field orientation="horizontal" className="justify-between">
            {label && <QuillChartOptionLabel htmlFor={id} label={label} info={info} />}
            <Select<T>
                value={value}
                onValueChange={(next: T | null) => next !== null && onChange(next)}
                disabled={!!disabledReason}
            >
                <SelectTrigger
                    id={id}
                    className={label ? undefined : 'w-full'}
                    render={<Button variant="outline" left disabledReason={disabledReason || undefined} />}
                    data-attr={dataAttr}
                >
                    <SelectValue>
                        {(selected: T) => options.find((option) => option.value === selected)?.label ?? selected}
                    </SelectValue>
                </SelectTrigger>
                <SelectContent align="start" alignItemWithTrigger={false}>
                    {options.map((option) => (
                        <SelectItem key={String(option.value)} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </Field>
    )
}
