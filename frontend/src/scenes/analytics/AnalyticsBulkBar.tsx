import { useActions, useValues } from 'kea'

import { IconChevronDown, IconFolderMove, IconX } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Text } from '@posthog/quill'

import { analyticsSelectionLogic } from './analyticsSelectionLogic'
import { analyticsShareLogic } from './analyticsShareLogic'

/** Acts on every row picked in the Analytics list at once. Shows only while something is picked. */
export function AnalyticsBulkBar(): JSX.Element | null {
    const { selectedItems, taggableSelectedItems, selectedTags } = useValues(analyticsSelectionLogic)
    const { clearSelection, openBulkTags } = useActions(analyticsSelectionLogic)
    const { openBulkShareToSpace } = useActions(analyticsShareLogic)
    if (!selectedItems.length) {
        return null
    }
    const noTaggable = taggableSelectedItems.length ? undefined : 'Only dashboards and insights have tags'
    return (
        <div
            data-quill-inverted
            role="toolbar"
            aria-label="Bulk actions"
            className="flex flex-wrap items-center gap-2 self-center rounded-lg bg-background px-3 py-2 text-foreground"
            data-attr="analytics-bulk-bar"
        >
            <Text size="sm" weight="medium" className="tabular-nums">
                {`${selectedItems.length} selected`}
            </Text>
            <Button
                variant="outline"
                onClick={() =>
                    openBulkShareToSpace(
                        selectedItems.map((item) => ({ type: item.type, ref: item.id, name: item.name }))
                    )
                }
                data-attr="analytics-bulk-add-to-collection"
            >
                <IconFolderMove />
                Add to collection
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={<Button variant="outline" disabledReason={noTaggable} data-attr="analytics-bulk-tags" />}
                >
                    Tags
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="min-w-48">
                    <DropdownMenuItem onClick={() => openBulkTags('add')} data-attr="analytics-bulk-tags-add">
                        Add tags…
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        onClick={() => openBulkTags('remove')}
                        disabledReason={selectedTags.length ? undefined : 'None of the selected items have tags'}
                        data-attr="analytics-bulk-tags-remove"
                    >
                        Remove tags…
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <Button
                size="icon"
                variant="outline"
                aria-label="Clear selection"
                tooltip="Clear selection"
                onClick={() => clearSelection()}
                data-attr="analytics-bulk-clear"
            >
                <IconX />
            </Button>
        </div>
    )
}
