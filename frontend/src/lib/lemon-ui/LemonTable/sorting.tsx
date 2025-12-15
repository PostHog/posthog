import { forwardRef } from 'react'

import { IconSort } from '@posthog/icons'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

/** Sorting state. */
export interface Sorting {
    columnKey: string
    /** 1 means ascending, -1 means descending. */
    order: 1 | -1
}

export function getNextSorting(
    currentSorting: Sorting | null,
    selectedColumnKey: string,
    disableSortingCancellation: boolean
): Sorting | null {
    if (
        !currentSorting ||
        currentSorting.columnKey !== selectedColumnKey ||
        (currentSorting.order === -1 && disableSortingCancellation)
    ) {
        return { columnKey: selectedColumnKey, order: 1 }
    } else if (currentSorting.order === 1) {
        return { columnKey: selectedColumnKey, order: -1 }
    }
    return null
}

export const SortingIndicator: React.FunctionComponent<
    { order: Sorting['order'] | null } & React.RefAttributes<HTMLDivElement>
> = forwardRef(function SortingIndicator({ order }, ref): JSX.Element {
    return (
        <div ref={ref} className="flex items-center text-base ml-2 whitespace-nowrap">
            <IconSort />
            {order === -1 ? <IconArrowDown /> : order === 1 ? <IconArrowUp /> : null}
        </div>
    )
})
