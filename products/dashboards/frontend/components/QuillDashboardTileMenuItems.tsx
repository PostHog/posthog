import { DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

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
}: {
    editLabel: string
    editDataAttr: string
    onEdit: () => void
    placement: InsightCardMenuPlacement
    onDuplicate: () => void
    duplicateDataAttr: string
    onRemove?: () => void
    removeDataAttr: string
}): JSX.Element {
    return (
        <>
            <DropdownMenuItem onClick={onEdit} data-attr={editDataAttr}>
                {editLabel}
            </DropdownMenuItem>
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
