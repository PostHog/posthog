import { router } from 'kea-router'

import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import { QuillDashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/QuillDashboardWidgetPlacementMenus'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import type { WidgetCardMenu } from './widgetCardMenu'

export function QuillWidgetCardMenuItems({
    menu,
    widgetItems,
}: {
    menu: WidgetCardMenu
    widgetItems: JSX.Element | null
}): JSX.Element {
    const { viewUrl, edit, duplicate, dashboard, refresh } = menu
    const placement = dashboard?.placement
    const description = dashboard?.description
    const hasMore = !!placement || !!description || !!refresh

    return (
        <>
            {edit && (
                <DropdownMenuItem onClick={edit} data-attr="dashboard-widget-edit">
                    Edit
                </DropdownMenuItem>
            )}
            {viewUrl && <DropdownMenuItem onClick={() => router.actions.push(viewUrl)}>View</DropdownMenuItem>}
            {widgetItems}
            {duplicate && <DropdownMenuItem onClick={duplicate}>Duplicate</DropdownMenuItem>}
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
                                                <span>Last computed </span>
                                                <TZLabel time={dayjs(refresh.lastRefresh)} noStyles />
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
            {dashboard?.remove && (
                <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive" onClick={dashboard.remove}>
                        Remove from dashboard
                    </DropdownMenuItem>
                </>
            )}
        </>
    )
}
