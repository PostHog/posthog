import { ReactNode } from 'react'

import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

export interface QuillDisplayOptionSelectProps<T extends string | number> {
    value: T
    options: { value: T; label: ReactNode }[]
    onChange: (value: T) => void
    disabledReason?: string | null
    fullWidth?: boolean
    'data-attr'?: string
}

export function QuillDisplayOptionSelect<T extends string | number>({
    value,
    options,
    onChange,
    disabledReason,
    fullWidth,
    'data-attr': dataAttr,
}: QuillDisplayOptionSelectProps<T>): JSX.Element {
    return (
        <Select<T> value={value} onValueChange={(next) => next !== null && onChange(next)} disabled={!!disabledReason}>
            <SelectTrigger
                render={
                    <Button
                        variant="outline"
                        left
                        disabledReason={disabledReason}
                        className={fullWidth ? 'w-full' : undefined}
                    />
                }
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
    )
}
