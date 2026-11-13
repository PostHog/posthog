import { useValues } from 'kea'

import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import { QuillDashboardWidgetPlacementMenu } from 'lib/components/Cards/InsightCard/QuillDashboardWidgetPlacementMenu'

import { dashboardsModel } from '~/models/dashboardsModel'

import { type DashboardTileGroupMenuActions, TILE_GROUP_MENU_ITEMS } from './DashboardTileGroupMenuOverlay'

// Base UI's context menu is built from the same menu parts, so these rows render in both the dropdown and the context menu.
export function QuillDashboardTileGroupMenuItems({
    groupDisplay,
    addTileOptions,
    onStartRename,
    onRemove,
    groupHasTiles,
    onChangeGroupDisplay,
    copyToDestinations,
    onCopyToDashboard,
    copyLoading,
}: DashboardTileGroupMenuActions): JSX.Element {
    // Each rename sends every group, so a second rename before the first saves would undo it.
    const { dashboardLoading: dashboardSaving } = useValues(dashboardsModel)
    const { renameLabel, removeLabel, copyLabel, copyNoun, switchTo, switchLabel } = TILE_GROUP_MENU_ITEMS[groupDisplay]
    const savingReason = dashboardSaving ? 'Saving dashboard changes' : undefined
    const hasEditItems = !!onStartRename || !!onRemove

    return (
        <>
            {!!addTileOptions?.length && (
                <>
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger data-attr="dashboard-tile-group-menu-add">
                            Add tile
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            {addTileOptions.map((option) => (
                                <DropdownMenuItem
                                    key={option.key}
                                    onClick={option.onClick}
                                    data-attr={`dashboard-tile-group-menu-add-${option.key}`}
                                >
                                    {option.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    {(hasEditItems || onCopyToDashboard || onChangeGroupDisplay) && <DropdownMenuSeparator />}
                </>
            )}
            {onStartRename && (
                <DropdownMenuItem
                    onClick={onStartRename}
                    disabledReason={savingReason}
                    data-attr="dashboard-tile-group-menu-rename"
                >
                    {renameLabel}
                </DropdownMenuItem>
            )}
            {onRemove && (
                <DropdownMenuItem
                    variant="destructive"
                    onClick={onRemove}
                    disabledReason={
                        savingReason ??
                        (groupHasTiles ? `Move this ${copyNoun}'s tiles out before deleting it` : undefined)
                    }
                    data-attr="dashboard-tile-group-menu-remove"
                >
                    {removeLabel}
                </DropdownMenuItem>
            )}
            {hasEditItems && (onCopyToDashboard || onChangeGroupDisplay) && <DropdownMenuSeparator />}
            {onCopyToDashboard && (
                <>
                    <QuillDashboardWidgetPlacementMenu
                        label={copyLabel}
                        destinations={(copyToDestinations ?? []).map((destination) =>
                            copyLoading ? { ...destination, disabledReason: `Copying ${copyNoun}` } : destination
                        )}
                        onSelect={({ id, name }) => onCopyToDashboard(id, name || 'Untitled')}
                        emptyDisabledReason="No other dashboards"
                    />
                    {onChangeGroupDisplay && <DropdownMenuSeparator />}
                </>
            )}
            {onChangeGroupDisplay && (
                <DropdownMenuItem
                    onClick={() => onChangeGroupDisplay(switchTo)}
                    data-attr={`dashboard-tile-group-menu-group-display-${switchTo}`}
                >
                    {switchLabel}
                </DropdownMenuItem>
            )}
        </>
    )
}
