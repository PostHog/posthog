import { forwardRef } from 'react'

import { IconSort } from '@posthog/icons'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

/** Sorting state. */
export interface Sorting {
    columnKey: string
    /** 1 means ascending, -1 means descending. */
    order: 1 | -1
}

export function getNextSortings(
    currentSortings: Sorting[],
    selectedColumnKey: string,
    disableSortingCancellation: boolean,
    defaultOrder: 1 | -1 = 1
): Sorting[] {
    const currentSortingIndex = currentSortings.findIndex(({ columnKey }) => columnKey === selectedColumnKey)
    const nextSorting = getNextSorting(
        currentSortingIndex === -1 ? null : currentSortings[currentSortingIndex],
        selectedColumnKey,
        disableSortingCancellation,
        defaultOrder
    )

    if (currentSortingIndex === -1) {
        return nextSorting ? [...currentSortings, nextSorting] : currentSortings
    }

    if (!nextSorting) {
        return currentSortings.filter((_, index) => index !== currentSortingIndex)
    }

    return currentSortings.map((sorting, index) => (index === currentSortingIndex ? nextSorting : sorting))
}

export function compareWithSortings<T>(
    first: T,
    second: T,
    sortings: Sorting[],
    getComparator: (columnKey: string) => ((a: T, b: T) => number) | undefined
): number {
    for (const sorting of sortings) {
        const comparator = getComparator(sorting.columnKey)
        if (comparator) {
            const result = sorting.order * comparator(first, second)
            if (result !== 0) {
                return result
            }
        }
    }
    return 0
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
    { order: Sorting['order'] | null; priority?: number } & React.RefAttributes<HTMLDivElement>
> = forwardRef(function SortingIndicator({ order, priority }, ref): JSX.Element {
    return (
        <div ref={ref} className="sorting-indicator flex items-center text-base ml-2 whitespace-nowrap">
            {order === -1 ? <IconArrowDown /> : order === 1 ? <IconArrowUp /> : <IconSort />}
            {priority != null && <span className="ml-0.5 text-[10px] font-semibold tabular-nums">{priority}</span>}
        </div>
    )
})
