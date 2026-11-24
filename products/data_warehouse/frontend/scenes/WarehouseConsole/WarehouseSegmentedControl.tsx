import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

export interface SegmentedOption<T extends string> {
    value: T
    label: string
    'data-attr': string
}

/** The one segmented control of the console. A click on the active option does nothing. */
export function WarehouseSegmentedControl<T extends string>({
    value,
    options,
    onChange,
    label,
    disabled,
}: {
    value: T
    options: SegmentedOption<T>[]
    onChange: (value: T) => void
    label: string
    disabled?: boolean
}): JSX.Element {
    return (
        <ToggleGroup
            variant="outline"
            value={[value]}
            onValueChange={(next) => {
                const picked = next[0] as T | undefined
                if (picked && picked !== value) {
                    onChange(picked)
                }
            }}
            aria-label={label}
        >
            {options.map((option) => (
                <ToggleGroupItem
                    key={option.value}
                    value={option.value}
                    disabled={disabled}
                    data-attr={option['data-attr']}
                >
                    {option.label}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
