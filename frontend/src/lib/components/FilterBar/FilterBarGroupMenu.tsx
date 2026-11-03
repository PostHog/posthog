import { useActions } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { filterBarLogic } from './filterBarLogic'

export function FilterBarGroupMenu({ groupId }: { groupId: number }): JSX.Element {
    const { ungroupNode, duplicateGroup, removeItem } = useActions(filterBarLogic)
    return (
        <DropdownMenu modal={false}>
            <DropdownMenuTrigger
                render={<Button size="icon" aria-label="Group options" tooltip="Group options" />}
                data-attr="filter-bar-group-menu"
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuItem onClick={() => duplicateGroup(groupId)} data-attr="filter-bar-group-duplicate">
                    Duplicate group
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => ungroupNode(groupId)} data-attr="filter-bar-group-ungroup">
                    Ungroup
                </DropdownMenuItem>
                <DropdownMenuItem
                    variant="destructive"
                    onClick={() => removeItem(groupId)}
                    data-attr="filter-bar-group-remove"
                >
                    Remove group
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
