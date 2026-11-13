import type { ReactNode } from 'react'

import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import type { InsightCardMenuPlacement } from 'lib/components/Cards/InsightCard/insightCardMenu'
import { QuillDashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/QuillDashboardWidgetPlacementMenus'

export function QuillDashboardTileMenuItems({
    editLabel,
    editDataAttr,
    onEdit,
    placement,
    onDuplicate,
    duplicateDataAttr,
    onRemove,
    removeDataAttr,
    displayOptions,
}: {
    editLabel: string
    editDataAttr: string
    onEdit: () => void
    placement: InsightCardMenuPlacement
    onDuplicate: () => void
    duplicateDataAttr: string
    onRemove?: () => void
    removeDataAttr: string
    displayOptions?: ReactNode
}): JSX.Element {
    return (
        <>
            <DropdownMenuItem onClick={onEdit} data-attr={editDataAttr}>
                {editLabel}
            </DropdownMenuItem>
            {displayOptions && (
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger data-attr="dashboard-tile-display-options">
                        Display options
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent className="px-2 py-1">{displayOptions}</DropdownMenuSubContent>
                </DropdownMenuSub>
            )}
            <QuillDashboardWidgetPlacementMenus {...placement} />
            <DropdownMenuItem onClick={onDuplicate} data-attr={duplicateDataAttr}>
                Duplicate
            </DropdownMenuItem>
            {onRemove && (
                <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive" onClick={() => onRemove()} data-attr={removeDataAttr}>
                        Delete
                    </DropdownMenuItem>
                </>
            )}
        </>
    )
}
