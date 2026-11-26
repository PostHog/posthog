import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

export interface MatchingOption {
    value: string
    label: string
}

/** Picks how a match group field compares its value, for example "contains" or "matches regex". */
export function QuillActionStepMatchingToggle({
    label,
    options,
    value,
    onChange,
    disabledReason,
}: {
    /** What the toggle sets, for screen readers. */
    label: string
    options: MatchingOption[]
    value: string
    onChange: (value: string) => void
    disabledReason?: string
}): JSX.Element {
    return (
        <ToggleGroup
            variant="outline"
            size="sm"
            aria-label={label}
            value={[value]}
            onValueChange={(next: string[]) => {
                if (next[0]) {
                    onChange(next[0])
                }
            }}
        >
            {options.map((option) => (
                <ToggleGroupItem key={option.value} value={option.value} disabledReason={disabledReason}>
                    {option.label}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
