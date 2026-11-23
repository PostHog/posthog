import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

export interface QuillOption<T extends string | number> {
    value: T
    label: string
}

export function QuillOptionSelect<T extends string | number>({
    id,
    value,
    options,
    onChange,
    disabled,
    disabledReason,
    ariaLabel,
    placeholder,
    className,
    dataAttr,
}: {
    id?: string
    value: T | null | undefined
    options: QuillOption<T>[]
    onChange: (value: T) => void
    disabled?: boolean
    disabledReason?: React.ReactNode
    ariaLabel?: string
    placeholder?: string
    className?: string
    dataAttr?: string
}): JSX.Element {
    return (
        <Select
            value={value ?? null}
            onValueChange={(next) => next !== null && onChange(next as T)}
            disabled={disabled}
        >
            <SelectTrigger
                id={id}
                aria-label={ariaLabel}
                className={className}
                disabledReason={disabledReason}
                data-attr={dataAttr}
            >
                <SelectValue placeholder={placeholder}>
                    {(selected: T | null) => options.find((option) => option.value === selected)?.label}
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
