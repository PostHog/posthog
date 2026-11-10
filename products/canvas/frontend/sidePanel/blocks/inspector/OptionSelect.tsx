import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

export interface InspectorOption<T extends string = string> {
    value: T
    label: string
}

/** A dropdown of fixed options, for settings with more options than a segmented control fits. */
export function OptionSelect<T extends string>({
    value,
    options,
    onChange,
    ariaLabel,
}: {
    value: T
    options: InspectorOption<T>[]
    onChange: (value: T) => void
    ariaLabel: string
}): JSX.Element {
    const labelOf = (selected: T): string => options.find((option) => option.value === selected)?.label ?? selected
    return (
        <Select
            value={value}
            onValueChange={(next: T | null) => {
                if (next) {
                    onChange(next)
                }
            }}
        >
            <SelectTrigger aria-label={ariaLabel} size="sm" className="w-full">
                <SelectValue>{(selected: T) => labelOf(selected)}</SelectValue>
            </SelectTrigger>
            <SelectContent align="start" side="bottom" sideOffset={4}>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
