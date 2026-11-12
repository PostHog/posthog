import { router } from 'kea-router'

import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import type { InsightCardMenuPlacement } from 'lib/components/Cards/InsightCard/insightCardMenu'
import { QuillDashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/QuillDashboardWidgetPlacementMenus'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs, type Dayjs } from 'lib/dayjs'

export type QuillWidgetCardMenuItemsProps = {
    widgetItems?: JSX.Element | null
    viewUrl?: string
    onEdit?: () => void
    onDuplicate?: () => void
    description?: { label: string; onClick: () => void }
    placement?: InsightCardMenuPlacement
    refresh?: { onRefresh: () => void; disabledReason?: string; lastRefresh?: string | number | Dayjs | null }
    onRemove?: () => void
}

export function QuillWidgetCardMenuItems({
    widgetItems,
    viewUrl,
    onEdit,
    onDuplicate,
    description,
    placement,
    refresh,
    onRemove,
}: QuillWidgetCardMenuItemsProps): JSX.Element {
    const hasMore = !!description || !!placement || !!refresh

    return (
        <>
            {onEdit && (
                <DropdownMenuItem onClick={onEdit} data-attr="dashboard-widget-edit">
                    Edit
                </DropdownMenuItem>
            )}
            {viewUrl && <DropdownMenuItem onClick={() => router.actions.push(viewUrl)}>View</DropdownMenuItem>}
            {widgetItems}
            {onDuplicate && <DropdownMenuItem onClick={onDuplicate}>Duplicate</DropdownMenuItem>}
            {hasMore && (
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger data-attr="dashboard-widget-more-menu">More</DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                        {placement && <QuillDashboardWidgetPlacementMenus {...placement} />}
                        {description && (
                            <>
                                {placement && <DropdownMenuSeparator />}
                                <DropdownMenuItem onClick={description.onClick}>{description.label}</DropdownMenuItem>
                            </>
                        )}
                        {refresh && (
                            <>
                                {(placement || description) && <DropdownMenuSeparator />}
                                <DropdownMenuItem
                                    onClick={refresh.onRefresh}
                                    disabledReason={refresh.disabledReason}
                                    description={
                                        refresh.lastRefresh != null ? (
                                            <>
                                                Last computed <TZLabel time={dayjs(refresh.lastRefresh)} noStyles />
                                            </>
                                        ) : undefined
                                    }
                                    data-attr="dashboard-tile-refresh-data"
                                >
                                    Refresh data
                                </DropdownMenuItem>
                            </>
                        )}
                    </DropdownMenuSubContent>
                </DropdownMenuSub>
            )}
            {onRemove && (
                <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive" onClick={() => onRemove()}>
                        Remove from dashboard
                    </DropdownMenuItem>
                </>
            )}
        </>
    )
}
