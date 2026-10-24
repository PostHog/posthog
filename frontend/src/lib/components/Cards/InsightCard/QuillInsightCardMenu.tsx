import { useMountedLogic } from 'kea'
import { useRef, useState } from 'react'

import { IconEllipsis, IconWarning } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@posthog/quill'

import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import type { ExportButtonCopyToClipboardItem, ExportButtonItem } from 'lib/components/ExportButton/ExportButton'
import { exportItemAttributes } from 'lib/components/ExportButton/exportItemAttributes'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'
import { Splotch, SplotchColor } from 'lib/lemon-ui/Splotch'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { DisplayOptionTab } from '~/queries/nodes/InsightViz/insightDisplayOptions'
import { InsightDisplayOptionsPanel } from '~/queries/nodes/InsightViz/InsightDisplayOptionsPanel'
import { AccessControlLevel, AccessControlResourceType, DashboardBasicType, DashboardType, InsightColor } from '~/types'

import type { TileGroupMoveOptions } from 'products/dashboards/frontend/dashboardTileSections'

import { QuillDashboardWidgetPlacementSubmenu } from './QuillDashboardWidgetPlacementSubmenu'

export interface QuillInsightCardMenuProps {
    tooltip?: string
    onView?: () => void
    onCopyLink?: () => void
    copyLinkDataAttr?: string
    onEdit?: () => void
    /** Says that opening the editor discards the dashboard overrides the card shows. */
    editWarning?: string
    onDuplicate?: () => void
    duplicateDataAttr?: string
    onRename?: () => void
    placementDestinations: DashboardWidgetPlacementDestination[]
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onCopyToDashboard?: (dashboard: DashboardBasicType) => void
    tileGroupMoveOptions?: TileGroupMoveOptions
    onMoveToTileGroup?: (sectionKey: string | null) => void
    color?: InsightColor | null
    onSetColor?: (color: InsightColor) => void
    /** Set when the card has a description that can be shown or hidden. */
    descriptionShown?: boolean
    onToggleDescription?: () => void
    /** Chart type pickers and display option tabs, computed by the always-mounted card meta. */
    visualizationItems?: LemonMenuItems
    displayOptionTabs?: DisplayOptionTab[]
    lastRefresh?: string | null
    onRefresh?: () => void
    refreshDisabledReason?: string
    onSetOverride?: () => void
    onOpenAlerts?: () => void
    exportItems?: ExportButtonItem[]
    copyToClipboardItems?: ExportButtonCopyToClipboardItem[]
    onCopyImage: () => void
    copyImageDisabledReason?: string
    onRemoveFromDashboard?: () => void
    onDeleteInsight?: () => void
}

/**
 * Lemon popovers inside the display options panel open in a portal outside the quill popover.
 * A press or a focus move into them must not close the panel.
 */
function isInLemonOverlay(target: EventTarget | null | undefined): boolean {
    return target instanceof Element && !!target.closest('.Popover, .LemonModal__container')
}

/**
 * The "⋯" menu of an insight card on the today-rail-nav path. View, Edit and Duplicate stay at the top.
 * The other actions are in Organize, Display, Data and Export submenus, and the destructive action is last.
 */
export function QuillInsightCardMenu({
    tooltip,
    onView,
    onCopyLink,
    copyLinkDataAttr,
    onEdit,
    editWarning,
    onDuplicate,
    duplicateDataAttr,
    onRename,
    placementDestinations,
    onMoveToDashboard,
    onCopyToDashboard,
    tileGroupMoveOptions,
    onMoveToTileGroup,
    color,
    onSetColor,
    descriptionShown,
    onToggleDescription,
    visualizationItems = [],
    displayOptionTabs = [],
    lastRefresh,
    onRefresh,
    refreshDisabledReason,
    onSetOverride,
    onOpenAlerts,
    exportItems,
    copyToClipboardItems,
    onCopyImage,
    copyImageDisabledReason,
    onRemoveFromDashboard,
    onDeleteInsight,
}: QuillInsightCardMenuProps): JSX.Element {
    useMountedLogic(exportsLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [displayOptionsOpen, setDisplayOptionsOpen] = useState(false)

    const hasDisplayOptions = visualizationItems.length > 0 || displayOptionTabs.length > 0
    const hasOrganize = !!onRename || !!onMoveToDashboard || !!onCopyToDashboard || !!onSetColor
    const hasDisplay = hasDisplayOptions || !!onToggleDescription
    const hasData = !!onRefresh || !!onSetOverride || !!onOpenAlerts
    const exportDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Export, AccessControlLevel.Editor) ?? undefined

    return (
        <span className="relative inline-flex" data-quill>
            <DropdownMenu>
                <DropdownMenuTrigger
                    ref={triggerRef}
                    render={
                        <Button size="icon-sm" aria-label="More actions" tooltip={tooltip} data-attr="more-button" />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuGroup>
                        {onView && <DropdownMenuItem onClick={onView}>View</DropdownMenuItem>}
                        {onEdit && (
                            <DropdownMenuItem onClick={onEdit} tooltip={editWarning}>
                                {editWarning && <IconWarning />}
                                Edit
                            </DropdownMenuItem>
                        )}
                        {onDuplicate && (
                            <DropdownMenuItem onClick={onDuplicate} data-attr={duplicateDataAttr}>
                                Duplicate
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    {hasOrganize && (
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger>Organize</DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                {onRename && <DropdownMenuItem onClick={onRename}>Rename</DropdownMenuItem>}
                                {onMoveToDashboard && (
                                    <QuillDashboardWidgetPlacementSubmenu
                                        label="Move to"
                                        destinations={placementDestinations}
                                        onSelect={(dashboard) =>
                                            onMoveToDashboard({ id: dashboard.id, name: dashboard.name })
                                        }
                                        emptyDisabledReason="No dashboards you can move to"
                                        tileGroupMoveOptions={tileGroupMoveOptions}
                                        onMoveToTileGroup={onMoveToTileGroup}
                                    />
                                )}
                                {onCopyToDashboard && (
                                    <QuillDashboardWidgetPlacementSubmenu
                                        label="Copy to"
                                        destinations={placementDestinations}
                                        onSelect={onCopyToDashboard}
                                        emptyDisabledReason="No dashboards you can copy to"
                                    />
                                )}
                                {onSetColor && (
                                    <DropdownMenuSub>
                                        <DropdownMenuSubTrigger>Set color</DropdownMenuSubTrigger>
                                        <DropdownMenuSubContent>
                                            <DropdownMenuRadioGroup
                                                value={color || InsightColor.White}
                                                onValueChange={(next: InsightColor) => onSetColor(next)}
                                            >
                                                {Object.values(InsightColor).map((availableColor) => (
                                                    <DropdownMenuRadioItem key={availableColor} value={availableColor}>
                                                        {availableColor !== InsightColor.White && (
                                                            <Splotch color={availableColor as string as SplotchColor} />
                                                        )}
                                                        {availableColor !== InsightColor.White
                                                            ? capitalizeFirstLetter(availableColor)
                                                            : 'No color'}
                                                    </DropdownMenuRadioItem>
                                                ))}
                                            </DropdownMenuRadioGroup>
                                        </DropdownMenuSubContent>
                                    </DropdownMenuSub>
                                )}
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                    {hasDisplay && (
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger>Display</DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                {hasDisplayOptions && (
                                    <DropdownMenuItem onClick={() => setDisplayOptionsOpen(true)}>
                                        Display options…
                                    </DropdownMenuItem>
                                )}
                                {onToggleDescription && (
                                    <DropdownMenuItem onClick={onToggleDescription}>
                                        {descriptionShown ? 'Hide description' : 'Show description'}
                                    </DropdownMenuItem>
                                )}
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                    {hasData && (
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger>Data</DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                <DropdownMenuGroup>
                                    {lastRefresh && (
                                        <DropdownMenuLabel>
                                            <span>Last computed </span>
                                            <TZLabel time={lastRefresh} noStyles />
                                        </DropdownMenuLabel>
                                    )}
                                    {onRefresh && (
                                        <DropdownMenuItem
                                            onClick={onRefresh}
                                            disabledReason={refreshDisabledReason}
                                            data-attr="dashboard-tile-refresh-data"
                                        >
                                            Refresh data
                                        </DropdownMenuItem>
                                    )}
                                    {onSetOverride && (
                                        <DropdownMenuItem onClick={onSetOverride}>Set override</DropdownMenuItem>
                                    )}
                                    {onOpenAlerts && (
                                        <DropdownMenuItem
                                            onClick={onOpenAlerts}
                                            data-attr="dashboard-insight-manage-alerts"
                                        >
                                            Alerts
                                        </DropdownMenuItem>
                                    )}
                                </DropdownMenuGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger data-attr="export-button">Export</DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            {exportItems && exportItems.length > 0 && (
                                <>
                                    <DropdownMenuGroup>
                                        <DropdownMenuLabel>File type</DropdownMenuLabel>
                                        {exportItems.map(({ title, ...triggerExportProps }) => {
                                            const { extension, target, body } = exportItemAttributes(triggerExportProps)
                                            return (
                                                <DropdownMenuItem
                                                    key={extension}
                                                    onClick={() => exportsLogic.actions.startExport(triggerExportProps)}
                                                    disabledReason={exportDisabledReason}
                                                    data-attr={`export-button-${extension}`}
                                                    data-ph-capture-attribute-export-target={target}
                                                    data-ph-capture-attribute-export-body={body}
                                                >
                                                    {title ?? `.${extension}`}
                                                </DropdownMenuItem>
                                            )
                                        })}
                                    </DropdownMenuGroup>
                                    <DropdownMenuSeparator />
                                </>
                            )}
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Copy to clipboard</DropdownMenuLabel>
                                {copyToClipboardItems?.map((item) => (
                                    <DropdownMenuItem
                                        key={item.title}
                                        onClick={item.onClick}
                                        disabledReason={item.disabledReason}
                                        data-attr={item['data-attr']}
                                    >
                                        {item.title}
                                    </DropdownMenuItem>
                                ))}
                                <DropdownMenuItem
                                    onClick={onCopyImage}
                                    disabledReason={copyImageDisabledReason}
                                    data-attr="insight-card-copy-image"
                                >
                                    PNG image
                                </DropdownMenuItem>
                                {onCopyLink && (
                                    <DropdownMenuItem onClick={onCopyLink} data-attr={copyLinkDataAttr}>
                                        Link to insight
                                    </DropdownMenuItem>
                                )}
                            </DropdownMenuGroup>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    {(onRemoveFromDashboard || onDeleteInsight) && (
                        <>
                            <DropdownMenuSeparator />
                            {onRemoveFromDashboard ? (
                                <DropdownMenuItem variant="destructive" onClick={onRemoveFromDashboard}>
                                    Remove from dashboard
                                </DropdownMenuItem>
                            ) : (
                                <DropdownMenuItem variant="destructive" onClick={onDeleteInsight}>
                                    Delete insight
                                </DropdownMenuItem>
                            )}
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
            {hasDisplayOptions && (
                <Popover
                    open={displayOptionsOpen}
                    onOpenChange={(open, details) => {
                        if (
                            !open &&
                            (details.reason === 'outside-press' || details.reason === 'focus-out') &&
                            (isInLemonOverlay(details.event?.target) ||
                                isInLemonOverlay((details.event as FocusEvent | undefined)?.relatedTarget))
                        ) {
                            return
                        }
                        setDisplayOptionsOpen(open)
                    }}
                >
                    {/* The panel opens from a menu row, so it anchors to an inert copy of the "⋯" button's box. */}
                    <PopoverTrigger
                        nativeButton={false}
                        tabIndex={-1}
                        aria-hidden
                        render={<span className="pointer-events-none absolute inset-0" />}
                    />
                    <PopoverContent
                        align="end"
                        finalFocus={triggerRef}
                        className="w-auto max-w-(--available-width) p-1"
                    >
                        {visualizationItems.length > 0 && <LemonMenuOverlay items={visualizationItems} />}
                        {visualizationItems.length > 0 && displayOptionTabs.length > 0 && <LemonDivider />}
                        <InsightDisplayOptionsPanel tabs={displayOptionTabs} />
                    </PopoverContent>
                </Popover>
            )}
        </span>
    )
}
