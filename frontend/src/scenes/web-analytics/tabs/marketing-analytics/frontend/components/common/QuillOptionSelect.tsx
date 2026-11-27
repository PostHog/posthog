import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

export interface QuillSelectOption<T extends string | number> {
    value: T
    label: string
    disabledReason?: string
}

export function QuillOptionSelect<T extends string | number>({
    value,
    onChange,
    options,
    ariaLabel,
    className,
    dataAttr,
    disabledReason,
}: {
    value: T | null
    onChange: (value: T) => void
    options: QuillSelectOption<T>[]
    ariaLabel: string
    className?: string
    dataAttr?: string
    disabledReason?: string | null
}): JSX.Element {
    return (
        <Select<T> value={value} onValueChange={(next) => next !== null && onChange(next)}>
            <SelectTrigger
                aria-label={ariaLabel}
                className={className}
                data-attr={dataAttr}
                disabledReason={disabledReason}
            >
                <SelectValue>
                    {(selected: T | null) => options.find((option) => option.value === selected)?.label}
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value} disabledReason={option.disabledReason}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
