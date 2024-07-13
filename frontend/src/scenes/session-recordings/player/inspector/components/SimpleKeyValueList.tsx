// A React component that renders a list of key-value pairs in a simple way.

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useEffect, useState } from 'react'

export interface SimpleKeyValueListProps {
    item: Record<string, any>
    emptyMessage?: string | JSX.Element | null
    /**
     * SimpleKeyValueList will render these keys first.
     * keys are otherwise rendered in alphabetical order.
     */
    promotedKeys?: string[]
}

export function SimpleKeyValueList({
    item,
    emptyMessage = 'No properties to display',
    promotedKeys,
}: SimpleKeyValueListProps): JSX.Element {
    const [sortedItemsPromotedFirst, setSortedItemsPromotedFirst] = useState<[string, any][]>([])

    useEffect(() => {
        const sortedItems = Object.entries(item).sort((a, b) => {
            if (a[0] < b[0]) {
                return -1
            }
            if (a[0] > b[0]) {
                return 1
            }
            return 0
        })

        // promoted items are shown in the order provided
        const promotedItems = promotedKeys?.length
            ? Object.entries(item)
                  .filter(([key]) => promotedKeys.includes(key))
                  .sort((a, b) => promotedKeys.indexOf(a[0]) - promotedKeys.indexOf(b[0]))
            : []
        // all other keys are provided sorted by key
        const nonPromotedItems = promotedKeys?.length
            ? sortedItems.filter(([key]) => !promotedKeys.includes(key))
            : sortedItems

        setSortedItemsPromotedFirst([...promotedItems, ...nonPromotedItems])
    }, [item, promotedKeys])

    return (
        <div className="text-xs space-y-1 max-w-full">
            {sortedItemsPromotedFirst.map(([key, value]) => (
                <div key={key} className="flex gap-4 items-start justify-between overflow-hidden">
                    <span className="font-semibold">
                        <PropertyKeyInfo value={key} />
                    </span>
                    <pre className="text-primary-alt break-all mb-0">{JSON.stringify(value, null, 2)}</pre>
                </div>
            ))}
            {Object.keys(item).length === 0 && emptyMessage}
        </div>
    )
}
