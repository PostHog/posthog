import { useActions, useValues } from 'kea'

import { IconSort } from '@posthog/icons'
import { Button, TableHead, cn } from '@posthog/quill'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import { SortDirection, TablesSortColumn } from '../catalogTableRows'
import { catalogTablesLogic } from '../catalogTablesLogic'

const ARIA_SORT: Record<SortDirection, 'ascending' | 'descending'> = { asc: 'ascending', desc: 'descending' }

interface CatalogTablesSortableHeadProps {
    column: TablesSortColumn
    label: string
    className?: string
    expand?: boolean
}

export function CatalogTablesSortableHead({
    column,
    label,
    className,
    expand,
}: CatalogTablesSortableHeadProps): JSX.Element {
    const { sort } = useValues(catalogTablesLogic)
    const { toggleSort } = useActions(catalogTablesLogic)
    const direction = sort?.column === column ? sort.direction : null

    return (
        <TableHead className={className} expand={expand} aria-sort={direction ? ARIA_SORT[direction] : undefined}>
            <Button
                size="sm"
                aria-selected={direction ? true : undefined}
                className={cn('-ml-2 gap-1.5', direction ? 'text-foreground' : 'hover:bg-fill-hover/50')}
                onClick={() => toggleSort(column)}
                data-attr={`data-catalog-tables-sort-${column}`}
            >
                {label}
                {direction === 'asc' ? (
                    <IconArrowUp className="size-3" />
                ) : direction === 'desc' ? (
                    <IconArrowDown className="size-3" />
                ) : (
                    <IconSort className="size-3 opacity-50" />
                )}
            </Button>
        </TableHead>
    )
}
