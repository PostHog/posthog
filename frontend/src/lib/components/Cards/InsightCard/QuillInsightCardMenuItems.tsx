import clsx from 'clsx'
import { router } from 'kea-router'

import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import { QuillExportSubMenu } from 'lib/components/ExportButton/QuillExportSubMenu'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { InsightColor } from '~/types'

import type { InsightCardMenu } from './insightCardMenu'
import { QuillDashboardInsightDisplayOptions } from './QuillDashboardInsightDisplayOptions'
import { QuillDashboardWidgetPlacementMenus } from './QuillDashboardWidgetPlacementMenus'

const SWATCH_CLASSES: Record<InsightColor, string> = {
    [InsightColor.White]: '',
    [InsightColor.Black]: 'bg-[var(--black)]',
    [InsightColor.Blue]: 'bg-[var(--blue)]',
    [InsightColor.Green]: 'bg-[var(--green)]',
    [InsightColor.Purple]: 'bg-[var(--purple)]',
}

export function QuillInsightCardMenuItems({ menu }: { menu: InsightCardMenu }): JSX.Element {
    const { dashboard, view, edit, duplicate, refresh } = menu
    return (
        <>
            {view && (
                <>
                    <DropdownMenuItem onClick={() => router.actions.push(view.url)}>View</DropdownMenuItem>
                    <DropdownMenuItem onClick={view.onCopyLink} data-attr={view.copyLinkDataAttr}>
                        Copy link
                    </DropdownMenuItem>
                </>
            )}
            {edit && (
                <DropdownMenuItem
                    onClick={() => router.actions.push(edit.url)}
                    tooltip={
                        typeof edit.overrideWarning.tooltip === 'function'
                            ? edit.overrideWarning.tooltip()
                            : edit.overrideWarning.tooltip
                    }
                >
                    {edit.overrideWarning.icon}
                    Edit
                </DropdownMenuItem>
            )}
            {menu.rename && <DropdownMenuItem onClick={menu.rename}>Rename</DropdownMenuItem>}
            {menu.setOverride && <DropdownMenuItem onClick={menu.setOverride}>Set override</DropdownMenuItem>}
            {duplicate && (
                <DropdownMenuItem onClick={duplicate.onClick} data-attr={duplicate.dataAttr}>
                    Duplicate
                </DropdownMenuItem>
            )}
            {menu.openAlerts && (
                <DropdownMenuItem onClick={menu.openAlerts} data-attr="dashboard-insight-manage-alerts">
                    Alerts
                </DropdownMenuItem>
            )}
            {menu.displayOptions && (
                <QuillDashboardInsightDisplayOptions
                    visualizationItems={menu.displayOptions.visualizationItems}
                    tabs={menu.displayOptions.tabs}
                />
            )}

            {menu.viewerPlacement && (
                <>
                    <DropdownMenuSeparator />
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Dashboard</DropdownMenuLabel>
                        <QuillDashboardWidgetPlacementMenus {...menu.viewerPlacement} />
                    </DropdownMenuGroup>
                </>
            )}

            {dashboard && (dashboard.description || dashboard.color || dashboard.placement) && (
                <>
                    <DropdownMenuSeparator />
                    {dashboard.description && (
                        <DropdownMenuItem onClick={dashboard.description.toggle}>
                            {dashboard.description.shown ? 'Hide description' : 'Show description'}
                        </DropdownMenuItem>
                    )}
                    {dashboard.color && (
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger>Set color</DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                <DropdownMenuRadioGroup
                                    value={dashboard.color.current}
                                    onValueChange={(color: InsightColor) => dashboard.color?.update(color)}
                                >
                                    {Object.values(InsightColor).map((color) => (
                                        <DropdownMenuRadioItem key={color} value={color}>
                                            {color !== InsightColor.White && (
                                                <span className={clsx('size-3 rounded-full', SWATCH_CLASSES[color])} />
                                            )}
                                            {color !== InsightColor.White ? capitalizeFirstLetter(color) : 'No color'}
                                        </DropdownMenuRadioItem>
                                    ))}
                                </DropdownMenuRadioGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                    {dashboard.placement && (
                        <>
                            {(dashboard.description || dashboard.color) && <DropdownMenuSeparator />}
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Dashboard</DropdownMenuLabel>
                                <QuillDashboardWidgetPlacementMenus {...dashboard.placement} />
                                {dashboard.placement.removeFromDashboard && (
                                    <DropdownMenuItem
                                        variant="destructive"
                                        onClick={dashboard.placement.removeFromDashboard}
                                    >
                                        Remove from dashboard
                                    </DropdownMenuItem>
                                )}
                            </DropdownMenuGroup>
                        </>
                    )}
                </>
            )}

            {menu.deleteInsight && (
                <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive" onClick={menu.deleteInsight}>
                        Delete insight
                    </DropdownMenuItem>
                </>
            )}

            <DropdownMenuSeparator />
            {menu.export && (
                <QuillExportSubMenu items={menu.export.items} copyToClipboardItems={menu.export.copyToClipboardItems} />
            )}
            <DropdownMenuItem
                onClick={menu.copyImage.onClick}
                disabledReason={menu.copyImage.disabledReason}
                tooltip="Copy the tile to your clipboard as a PNG"
                data-attr="insight-card-copy-image"
            >
                Copy as PNG
            </DropdownMenuItem>
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
        </>
    )
}
