import { useActions } from 'kea'

import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import { QuillDashboardWidgetPlacementMenu } from 'lib/components/Cards/InsightCard/QuillDashboardWidgetPlacementMenu'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { dashboardsModel } from '~/models/dashboardsModel'

import { type DashboardTileGroupMenuActions, useTileGroupMenuRows } from './DashboardTileGroupMenuOverlay'

// Base UI's context menu is built from the same menu parts, so these rows render in both the dropdown and the context menu.
export function QuillDashboardTileGroupMenuItems(actions: DashboardTileGroupMenuActions): JSX.Element {
    const { addTileOptions, onStartRename, onRemove, onChangeGroupDisplay, onCopyToDashboard } = actions
    const {
        labels: { renameLabel, removeLabel, copyLabel, switchTo, switchLabel },
        savingReason,
        removeDisabledReason,
        copyDestinations,
        onSelectCopyDestination,
        separatorAfterAdd,
        separatorAfterEdit,
        separatorAfterCopy,
    } = useTileGroupMenuRows(actions)
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)

    // The copy row shows "No other dashboards" until the list loads, so start loading as soon as the menu opens.
    useOnMountEffect(() => {
        if (onCopyToDashboard) {
            loadDashboardsIfNeeded()
        }
    })

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
                    {separatorAfterAdd && <DropdownMenuSeparator />}
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
                    disabledReason={removeDisabledReason}
                    data-attr="dashboard-tile-group-menu-remove"
                >
                    {removeLabel}
                </DropdownMenuItem>
            )}
            {separatorAfterEdit && <DropdownMenuSeparator />}
            {onCopyToDashboard && (
                <>
                    <QuillDashboardWidgetPlacementMenu
                        label={copyLabel}
                        destinations={copyDestinations}
                        onSelect={onSelectCopyDestination}
                        emptyDisabledReason="No other dashboards"
                    />
                    {separatorAfterCopy && <DropdownMenuSeparator />}
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
