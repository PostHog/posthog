import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

export interface QuillFilterRowSelectProps<T extends string | number> {
    value: T
    options: { value: T; label: string }[]
    onChange: (value: T) => void
    'data-attr'?: string
}

export function QuillFilterRowSelect<T extends string | number>({
    value,
    options,
    onChange,
    'data-attr': dataAttr,
}: QuillFilterRowSelectProps<T>): JSX.Element {
    return (
        <Select<T> value={value} onValueChange={(next: T | null) => next !== null && onChange(next)}>
            <SelectTrigger render={<Button variant="outline" left />} data-attr={dataAttr}>
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
