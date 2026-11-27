import clsx from 'clsx'

import { IconArrowDown } from 'lib/lemon-ui/icons'

export interface SortHeaderProps {
    label: string
    /** Whether the list is sorted by this column. */
    active: boolean
    onSort: () => void
    'data-attr': string
}

// The lists sort largest first only, so a header picks its column and never flips the direction, and the sorted column's
// header does nothing. A LemonButton would replace the table header's type style, so this button inherits it instead.
export function SortHeader({ label, active, onSort, 'data-attr': dataAttr }: SortHeaderProps): JSX.Element {
    return (
        <button
            type="button"
            aria-pressed={active}
            onClick={active ? undefined : onSort}
            className={clsx(
                'inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 [font:inherit] [letter-spacing:inherit] [text-transform:inherit] hover:text-primary',
                active ? 'text-primary' : 'text-inherit'
            )}
            data-attr={dataAttr}
        >
            {label}
            {active ? <IconArrowDown className="text-sm" /> : null}
        </button>
    )
}
