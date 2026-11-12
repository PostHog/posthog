import { IconChevronRight } from '@posthog/icons'

import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { Splotch, SplotchColor } from 'lib/lemon-ui/Splotch'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { InsightColor } from '~/types'

import { DashboardInsightDisplayOptionsMenu } from './DashboardInsightDisplayOptionsMenu'
import { DashboardTileRefreshDataButton } from './DashboardTileRefreshDataButton'
import { DashboardWidgetPlacementMenus } from './DashboardWidgetPlacementMenus'
import type { InsightCardMenu } from './insightCardMenu'

export function InsightCardMoreButtons({
    menu,
    moreButtons,
}: {
    menu: InsightCardMenu
    moreButtons?: JSX.Element | null
}): JSX.Element {
    const { dashboard } = menu
    return (
        <>
            {menu.view && (
                <LemonButton
                    to={menu.view.url}
                    fullWidth
                    sideAction={{
                        icon: <IconLink />,
                        tooltip: 'Copy link to insight',
                        'aria-label': 'Copy link to insight',
                        'data-attr': menu.view.copyLinkDataAttr,
                        onClick: menu.view.onCopyLink,
                    }}
                >
                    View
                </LemonButton>
            )}
            {menu.edit && (
                <LemonButton to={menu.edit.url} fullWidth {...menu.edit.overrideWarning}>
                    Edit
                </LemonButton>
            )}
            {menu.rename && (
                <LemonButton onClick={menu.rename} fullWidth>
                    Rename
                </LemonButton>
            )}
            {menu.setOverride && (
                <LemonButton onClick={menu.setOverride} fullWidth>
                    Set override
                </LemonButton>
            )}
            {menu.duplicate && (
                <LemonButton onClick={menu.duplicate.onClick} fullWidth data-attr={menu.duplicate.dataAttr}>
                    Duplicate
                </LemonButton>
            )}
            {menu.openAlerts && (
                <LemonButton onClick={menu.openAlerts} fullWidth data-attr="dashboard-insight-manage-alerts">
                    Alerts
                </LemonButton>
            )}
            {menu.displayOptions && (
                <DashboardInsightDisplayOptionsMenu
                    visualizationItems={menu.displayOptions.visualizationItems}
                    tabs={menu.displayOptions.tabs}
                />
            )}

            {menu.viewerPlacement && (
                <>
                    <LemonDivider />
                    <h5 className="mx-2 my-1">Dashboard</h5>
                    <DashboardWidgetPlacementMenus
                        placementDestinations={menu.viewerPlacement.destinations}
                        onCopyToDashboard={menu.viewerPlacement.onCopyToDashboard}
                    />
                </>
            )}

            {dashboard && (
                <>
                    <LemonDivider />
                    {dashboard.description && (
                        <LemonButton onClick={dashboard.description.toggle} fullWidth>
                            {dashboard.description.shown ? 'Hide description' : 'Show description'}
                        </LemonButton>
                    )}
                    {dashboard.color && (
                        <LemonMenu
                            items={Object.values(InsightColor).map((availableColor) => ({
                                label: (
                                    <span className="flex items-center gap-2">
                                        {availableColor !== InsightColor.White ? (
                                            <Splotch color={availableColor as string as SplotchColor} />
                                        ) : null}
                                        <span>
                                            {availableColor !== InsightColor.White
                                                ? capitalizeFirstLetter(availableColor)
                                                : 'No color'}
                                        </span>
                                    </span>
                                ),
                                key: availableColor,
                                active: availableColor === dashboard.color?.current,
                                onClick: () => dashboard.color?.update(availableColor),
                            }))}
                            placement="right-start"
                            fallbackPlacements={['left-start']}
                            closeParentPopoverOnClickInside
                        >
                            <LemonButton fullWidth sideIcon={<IconChevronRight className="size-3" />}>
                                Set color
                            </LemonButton>
                        </LemonMenu>
                    )}
                    {dashboard.placement && (
                        <>
                            {(dashboard.description || dashboard.color) && <LemonDivider />}
                            <h5 className="mx-2 my-1">Dashboard</h5>
                            <DashboardWidgetPlacementMenus
                                placementDestinations={dashboard.placement.destinations}
                                onMoveToDashboard={dashboard.placement.onMoveToDashboard}
                                tileGroupMoveOptions={dashboard.placement.tileGroupMoveOptions}
                                onMoveToTileGroup={dashboard.placement.onMoveToTileGroup}
                                onCopyToDashboard={dashboard.placement.onCopyToDashboard}
                            />
                            {dashboard.placement.removeFromDashboard && (
                                <LemonButton
                                    status="danger"
                                    onClick={dashboard.placement.removeFromDashboard}
                                    fullWidth
                                >
                                    Remove from dashboard
                                </LemonButton>
                            )}
                        </>
                    )}
                </>
            )}

            {menu.deleteInsight && (
                <>
                    <LemonDivider />
                    <LemonButton status="danger" onClick={menu.deleteInsight} fullWidth>
                        Delete insight
                    </LemonButton>
                </>
            )}

            {menu.export && (
                <>
                    <LemonDivider />
                    <ExportButton
                        fullWidth
                        sideIcon={<IconChevronRight className="size-3" />}
                        items={menu.export.items}
                        copyToClipboardItems={menu.export.copyToClipboardItems}
                    />
                </>
            )}
            <LemonButton
                onClick={menu.copyImage.onClick}
                disabledReason={menu.copyImage.disabledReason}
                tooltip="Copy the tile to your clipboard as a PNG"
                fullWidth
                data-attr="insight-card-copy-image"
            >
                Copy as PNG
            </LemonButton>
            {menu.refresh && (
                <DashboardTileRefreshDataButton
                    onRefresh={menu.refresh.onRefresh}
                    disabledReason={menu.refresh.disabledReason}
                    lastRefresh={menu.refresh.lastRefresh}
                />
            )}
            {moreButtons && (
                <>
                    <LemonDivider />
                    {moreButtons}
                </>
            )}
        </>
    )
}
