import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import type { InsightCardMenuPlacement } from 'lib/components/Cards/InsightCard/insightCardMenu'
import { QuillDashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/QuillDashboardWidgetPlacementMenus'
import { QuillChartOptionSwitch } from 'lib/components/ChartOptions/QuillChartOptionSwitch'

export function QuillDashboardTileMenuItems({
    editLabel,
    editDataAttr,
    onEdit,
    placement,
    onDuplicate,
    duplicateDataAttr,
    onRemove,
    removeDataAttr,
    transparentBackground,
}: {
    editLabel: string
    editDataAttr: string
    onEdit: () => void
    placement: InsightCardMenuPlacement
    onDuplicate: () => void
    duplicateDataAttr: string
    onRemove?: () => void
    removeDataAttr: string
    transparentBackground?: { checked: boolean; onToggle: () => void }
}): JSX.Element {
    return (
        <>
            <DropdownMenuItem onClick={onEdit} data-attr={editDataAttr}>
                {editLabel}
            </DropdownMenuItem>
            {transparentBackground && (
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger data-attr="text-card-display-options">
                        Display options
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent className="px-2 py-1">
                        <QuillChartOptionSwitch
                            label="Transparent background"
                            checked={transparentBackground.checked}
                            onChange={transparentBackground.onToggle}
                            data-attr="text-card-menu-transparent-background"
                        />
                    </DropdownMenuSubContent>
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
