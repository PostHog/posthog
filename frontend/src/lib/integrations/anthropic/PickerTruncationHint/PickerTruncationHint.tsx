type PickerTruncationHintProps = {
    show: boolean
    optionCount: number
    label: string
}

export function PickerTruncationHint({ show, optionCount, label }: PickerTruncationHintProps): JSX.Element | null {
    if (!show) {
        return null
    }
    return (
        <div className="text-xs text-secondary mt-1 italic">
            Showing the first {optionCount} {label}. Refine the list in the Anthropic console if you don't see yours.
        </div>
    )
}
