import { IconPlus } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

/** The row that turns what was typed in the search field into a value, when the list does not offer it. */
export function FilterBarTypedValueItem({
    label,
    keepOpen,
    onPick,
}: {
    label: string
    /** Lists stay open to take more values; a single-value kind closes once it has its value. */
    keepOpen: boolean
    onPick: () => void
}): JSX.Element {
    return (
        <DropdownMenuItem closeOnClick={!keepOpen} onClick={onPick} data-attr="filter-bar-value-typed">
            <IconPlus />
            <span className="truncate">{label}</span>
        </DropdownMenuItem>
    )
}
