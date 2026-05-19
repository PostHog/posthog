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
    disableSortingCancellation: boolean,
    defaultOrder: 1 | -1 = 1
): Sorting | null {
    const oppositeOrder = (defaultOrder === 1 ? -1 : 1) as 1 | -1
    if (
        !currentSorting ||
        currentSorting.columnKey !== selectedColumnKey ||
        (currentSorting.order === oppositeOrder && disableSortingCancellation)
    ) {
        return { columnKey: selectedColumnKey, order: defaultOrder }
    } else if (currentSorting.order === defaultOrder) {
        return { columnKey: selectedColumnKey, order: oppositeOrder }
    }
    return null
}

export const SortingIndicator: React.FunctionComponent<
    { order: Sorting['order'] | null } & React.RefAttributes<HTMLDivElement>
> = forwardRef(function SortingIndicator({ order }, ref): JSX.Element {
    return (
        <div ref={ref} className="sorting-indicator flex items-center text-base ml-2 whitespace-nowrap">
            {order === -1 ? <IconArrowDown /> : order === 1 ? <IconArrowUp /> : <IconSort />}
        </div>
    )
})
