// A React component that renders a list of key-value pairs in a simple way.
import { ReactNode, useEffect, useState } from 'react'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

export interface SimpleKeyValueListProps {
    item: Record<string, any>
    emptyMessage?: ReactNode
    header?: ReactNode
    /**
     * SimpleKeyValueList will render these keys first.
     * keys are otherwise rendered in alphabetical order.
     */
    promotedKeys?: string[]
    sortItems?: boolean
}

export function SimpleKeyValueList({
    item,
    emptyMessage = 'No properties to display',
    promotedKeys,
    header,
    sortItems = true,
}: SimpleKeyValueListProps): JSX.Element {
    const [sortedItemsPromotedFirst, setSortedItemsPromotedFirst] = useState<[string, any][]>([])

    useEffect(() => {
        const sortedItems = sortItems
            ? Object.entries(item).sort((a, b) => {
                  // if this is a posthog property we want to sort by its label
                  const left = getCoreFilterDefinition(a[0], TaxonomicFilterGroupType.EventProperties)?.label || a[0]
                  const right = getCoreFilterDefinition(b[0], TaxonomicFilterGroupType.EventProperties)?.label || b[0]

                  if (left < right) {
                      return -1
                  }
                  if (left > right) {
                      return 1
                  }
                  return 0
              })
            : Object.entries(item)

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
    }, [item, promotedKeys, sortItems])

    return (
        <div className="text-xs deprecated-space-y-1 max-w-full">
            {header}
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
