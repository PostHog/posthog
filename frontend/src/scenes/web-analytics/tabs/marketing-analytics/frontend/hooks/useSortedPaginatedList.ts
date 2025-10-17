import { useEffect, useMemo, useState } from 'react'

interface SortedPaginatedListOptions<T> {
    items: T[]
    maxItemsToShow: number
    getId: (item: T) => string
    isItemConfigured: (item: T) => boolean
}

export function useSortedPaginatedList<T>({
    items,
    maxItemsToShow,
    getId,
    isItemConfigured,
}: SortedPaginatedListOptions<T>): {
    displayedItems: T[]
    sortedItems: T[]
    hasMoreItems: boolean
    showAll: boolean
    setShowAll: (value: boolean) => void
} {
    const [showAll, setShowAll] = useState(false)
    const [itemOrder, setItemOrder] = useState<string[] | null>(null)

    // Establish initial sort order on first render - preserve order after that
    useEffect(() => {
        if (itemOrder === null && items.length > 0) {
            const sorted = [...items].sort((a, b) => {
                const aConfigured = isItemConfigured(a)
                const bConfigured = isItemConfigured(b)

                // Configured items first
                if (aConfigured && !bConfigured) {
                    return -1
                }
                if (!aConfigured && bConfigured) {
                    return 1
                }
                return 0
            })
            setItemOrder(sorted.map((item) => getId(item)))
        } else if (items.length === 0) {
            setItemOrder(null)
        }
    }, [items, itemOrder, getId, isItemConfigured])

    // Apply the preserved order to current item data
    const sortedItems = useMemo(() => {
        if (!itemOrder) {
            return items
        }

        const itemMap = new Map(items.map((item) => [getId(item), item]))
        return itemOrder.map((id) => itemMap.get(id)).filter(Boolean) as T[]
    }, [items, itemOrder, getId])

    // Determine which items to display
    const displayedItems = showAll ? sortedItems : sortedItems.slice(0, maxItemsToShow)
    const hasMoreItems = sortedItems.length > maxItemsToShow

    return {
        displayedItems,
        sortedItems,
        hasMoreItems,
        showAll,
        setShowAll,
    }
}
