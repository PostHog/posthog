import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import type { InsightCardMenu } from './insightCardMenu'
import { QuillDashboardWidgetPlacementMenus } from './QuillDashboardWidgetPlacementMenus'
import { QuillInsightCardColorSubMenu } from './QuillInsightCardColorSubMenu'

export function QuillInsightCardMoreSubMenu({
    menu,
    showCopyImage,
}: {
    menu: InsightCardMenu
    showCopyImage: boolean
}): JSX.Element | null {
    const { view, dashboard, refresh } = menu
    const placement = dashboard?.placement ?? menu.viewerPlacement
    const hasNameGroup = !!menu.rename || !!view
    const hasStyleGroup = !!dashboard?.color || !!dashboard?.description
    const hasDataGroup = !!menu.setOverride || !!refresh || !!menu.openAlerts || showCopyImage

    if (!hasNameGroup && !placement && !hasStyleGroup && !hasDataGroup) {
        return null
    }

    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger data-attr="insight-card-more-menu">More</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                {menu.rename && <DropdownMenuItem onClick={menu.rename}>Rename</DropdownMenuItem>}
                {view && (
                    <DropdownMenuItem onClick={view.onCopyLink} data-attr={view.copyLinkDataAttr}>
                        Copy link
                    </DropdownMenuItem>
                )}

                {placement && (
                    <>
                        {hasNameGroup && <DropdownMenuSeparator />}
                        <QuillDashboardWidgetPlacementMenus {...placement} />
                    </>
                )}

                {hasStyleGroup && (
                    <>
                        {(hasNameGroup || !!placement) && <DropdownMenuSeparator />}
                        {dashboard?.color && <QuillInsightCardColorSubMenu {...dashboard.color} />}
                        {dashboard?.description && (
                            <DropdownMenuItem onClick={dashboard.description.toggle}>
                                {dashboard.description.shown ? 'Hide description' : 'Show description'}
                            </DropdownMenuItem>
                        )}
                    </>
                )}

                {hasDataGroup && (
                    <>
                        {(hasNameGroup || !!placement || hasStyleGroup) && <DropdownMenuSeparator />}
                        {menu.setOverride && (
                            <DropdownMenuItem onClick={menu.setOverride}>Set override</DropdownMenuItem>
                        )}
                        {showCopyImage && (
                            <DropdownMenuItem
                                onClick={menu.copyImage.onClick}
                                disabledReason={menu.copyImage.disabledReason}
                                tooltip="Copy the tile to your clipboard as a PNG"
                                data-attr="insight-card-copy-image"
                            >
                                Copy as PNG
                            </DropdownMenuItem>
                        )}
                        {refresh && (
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
                        )}
                        {menu.openAlerts && (
                            <DropdownMenuItem onClick={menu.openAlerts} data-attr="dashboard-insight-manage-alerts">
                                Alerts
                            </DropdownMenuItem>
                        )}
                    </>
                )}
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
