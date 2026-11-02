import { useActions } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { FilterLogicalOperator } from '~/types'

import { filterBarLogic } from './filterBarLogic'

/** The structural actions on one row. Each one moves the edit to the stacked editor, where nesting has room. */
export function FilterBarChipMenu({
    nodeId,
    wrapType,
    canAddProperty,
}: {
    nodeId: number
    wrapType?: FilterLogicalOperator | null
    canAddProperty?: boolean
}): JSX.Element | null {
    const { wrapNodeInGroup, addEventProperty } = useActions(filterBarLogic)
    if (!wrapType && !canAddProperty) {
        return null
    }
    return (
        <DropdownMenu modal={false}>
            <DropdownMenuTrigger
                render={<Button size="icon" variant="outline" aria-label="More options" tooltip="More options" />}
                data-attr="filter-bar-chip-menu"
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                {canAddProperty && (
                    <DropdownMenuItem
                        onClick={() => addEventProperty(nodeId)}
                        data-attr="filter-bar-event-add-property"
                    >
                        Add a property filter
                    </DropdownMenuItem>
                )}
                {wrapType && (
                    <DropdownMenuItem
                        onClick={() => wrapNodeInGroup(nodeId, wrapType)}
                        data-attr="filter-bar-chip-wrap"
                    >
                        Add an {wrapType === FilterLogicalOperator.Or ? 'OR' : 'AND'} condition
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
