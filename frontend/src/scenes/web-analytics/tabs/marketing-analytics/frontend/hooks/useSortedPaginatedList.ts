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
    const [orderedItems, setOrderedItems] = useState<string[] | null>(null)

    // Establish initial sort order on first render - preserve order after that
    useEffect(() => {
        if (items.length === 0) {
            setOrderedItems(null)
            return
        }
        const sortedItems = [...items].sort((a, b) => {
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
        setOrderedItems(sortedItems.map((item) => getId(item)))
    }, [items, getId, isItemConfigured])

    // Apply the preserved order to current item data
    const sortedItems = useMemo(() => {
        if (!orderedItems) {
            return items
        }

        const itemMap = new Map(items.map((item) => [getId(item), item]))
        return orderedItems.map((id) => itemMap.get(id)).filter(Boolean) as T[]
    }, [items, orderedItems, getId])

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
