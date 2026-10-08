import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import type { InspectorOption } from './OptionSelect'

/** A row of mutually exclusive options, for settings with a few short choices. */
export function Segmented<T extends string>({
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
    return (
        <ToggleGroup
            value={[value]}
            onValueChange={(next: string[]) => {
                const selected = next[0] as T | undefined
                if (selected && selected !== value) {
                    onChange(selected)
                }
            }}
            aria-label={ariaLabel}
            className="flex-wrap"
        >
            {options.map((option) => (
                <ToggleGroupItem key={option.value} value={option.value} size="sm" variant="outline">
                    {option.label}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
