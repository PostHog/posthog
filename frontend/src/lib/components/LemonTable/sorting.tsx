import clsx from 'clsx'
import { IconArrowDown, IconArrowUp, IconSort } from '../icons'

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
    } else {
        return null
    }
}

export function SortingIndicator({
    order,
    className,
}: {
    order: Sorting['order'] | null
    className?: string
}): JSX.Element {
    return (
        <div className={clsx('flex items-center text-base ml-2 whitespace-nowrap', className)}>
            <IconSort />
            {order === -1 ? <IconArrowDown /> : order === 1 ? <IconArrowUp /> : null}
        </div>
    )
}
