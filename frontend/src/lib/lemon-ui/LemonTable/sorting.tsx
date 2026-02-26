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

interface SortingIndicatorProps {
    order: Sorting['order'] | null
}

export function SortingIndicator({
    ref,
    order,
}: SortingIndicatorProps & React.RefAttributes<HTMLDivElement>): JSX.Element {
    return (
        <div ref={ref} className="sorting-indicator flex items-center text-base ml-2 whitespace-nowrap">
            {order === -1 ? <IconArrowDown /> : order === 1 ? <IconArrowUp /> : <IconSort />}
        </div>
    )
}
