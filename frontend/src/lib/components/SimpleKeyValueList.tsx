// A React component that renders a list of key-value pairs in a simple way.
import { ReactNode, useMemo, useState } from 'react'

import { JSONViewer } from 'lib/components/JSONViewer'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isObject } from 'lib/utils/guards'

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
    /**
     * Optional action rendered at the end of each row. The second argument is whether the row is
     * currently hovered, so the action can reveal itself on hover without reaching for a CSS class.
     */
    rowActions?: (key: string, isRowHovered: boolean) => ReactNode
}

function SimpleKeyValueRow({
    name,
    value,
    rowActions,
}: {
    name: string
    value: any
    rowActions?: (key: string, isRowHovered: boolean) => ReactNode
}): JSX.Element {
    const [isHovered, setIsHovered] = useState(false)
    const isComplexStructure = Array.isArray(value) || isObject(value)
    return (
        <div
            className="flex gap-4 items-start justify-between overflow-hidden"
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
        >
            <span className="font-semibold flex items-center gap-1 min-w-0">
                <PropertyKeyInfo value={name} />
                {rowActions ? rowActions(name, isHovered) : null}
            </span>
            {isComplexStructure ? (
                <JSONViewer src={value} collapsed={1} />
            ) : (
                <pre className="text-primary-alt break-all mb-0">{String(value)}</pre>
            )}
        </div>
    )
}

export function SimpleKeyValueList({
    item,
    emptyMessage = 'No properties to display',
    promotedKeys,
    header,
    sortItems = true,
    rowActions,
}: SimpleKeyValueListProps): JSX.Element {
    const sortedItemsPromotedFirst = useMemo(() => {
        const sortedItems = sortItems
            ? Object.entries(item).sort((a, b) => {
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

        const promotedItems = promotedKeys?.length
            ? Object.entries(item)
                  .filter(([key]) => promotedKeys.includes(key))
                  .sort((a, b) => promotedKeys.indexOf(a[0]) - promotedKeys.indexOf(b[0]))
            : []
        const nonPromotedItems = promotedKeys?.length
            ? sortedItems.filter(([key]) => !promotedKeys.includes(key))
            : sortedItems

        return [...promotedItems, ...nonPromotedItems]
    }, [item, promotedKeys, sortItems])

    return (
        <div className="text-xs deprecated-space-y-1 max-w-full">
            {header}
            {sortedItemsPromotedFirst.map(([key, value]) => (
                <SimpleKeyValueRow key={key} name={key} value={value} rowActions={rowActions} />
            ))}
            {Object.keys(item).length === 0 && emptyMessage}
        </div>
    )
}
