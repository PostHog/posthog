import { IconSort } from '@posthog/icons'
import { Button, TableHead, cn } from '@posthog/quill'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import { SortDirection } from '../catalogSort'

const ARIA_SORT: Record<SortDirection, 'ascending' | 'descending'> = { asc: 'ascending', desc: 'descending' }

export interface SortHeadProps {
    direction: SortDirection | null
    onToggle: () => void
    dataAttr: string
}

interface SortableTableHeadProps extends SortHeadProps {
    label: string
    tooltip?: string
    className?: string
    expand?: boolean
}

export function SortableTableHead({
    label,
    direction,
    onToggle,
    dataAttr,
    tooltip,
    className,
    expand,
}: SortableTableHeadProps): JSX.Element {
    return (
        <TableHead className={className} expand={expand} aria-sort={direction ? ARIA_SORT[direction] : undefined}>
            <Button
                size="sm"
                aria-selected={direction ? true : undefined}
                className={cn('-ml-2 gap-1.5', direction ? 'text-foreground' : 'hover:bg-fill-hover/50')}
                tooltip={tooltip}
                onClick={onToggle}
                data-attr={dataAttr}
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
