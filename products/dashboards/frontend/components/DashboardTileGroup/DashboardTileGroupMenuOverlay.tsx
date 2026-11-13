import { useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'

import { DashboardWidgetPlacementMenu } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { dashboardsModel } from '~/models/dashboardsModel'
import type { DashboardBasicType, TileGroupDisplay } from '~/types'

export const TILE_GROUP_MENU_ITEMS: Record<
    TileGroupDisplay,
    {
        renameLabel: string
        removeLabel: string
        copyLabel: string
        copyNoun: string
        switchTo: TileGroupDisplay
        switchLabel: string
    }
> = {
    sections: {
        renameLabel: 'Rename group',
        removeLabel: 'Delete group',
        copyLabel: 'Copy group to dashboard',
        copyNoun: 'group',
        switchTo: 'tabs',
        switchLabel: 'Show all groups as tabs',
    },
    tabs: {
        renameLabel: 'Rename tab',
        removeLabel: 'Delete tab',
        copyLabel: 'Copy tab to dashboard',
        copyNoun: 'tab',
        switchTo: 'sections',
        switchLabel: 'Show groups as sections',
    },
}

export interface DashboardTileGroupMenuActions {
    // Set by the caller to match where this menu renders: "sections" in the group header,
    // "tabs" in the tab bar. Not read from the dashboard's actual display mode.
    groupDisplay: TileGroupDisplay
    addTileOptions?: { key: string; label: string; onClick: () => void }[]
    onStartRename?: () => void
    onRemove?: () => void
    /** Removing a group never takes tiles out of it, so delete stays disabled until the group is empty. */
    groupHasTiles?: boolean
    onChangeGroupDisplay?: (groupDisplay: TileGroupDisplay) => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyToDashboard?: (dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
}

export function hasTileGroupMenuActions({
    addTileOptions,
    onStartRename,
    onRemove,
    onChangeGroupDisplay,
    onCopyToDashboard,
}: DashboardTileGroupMenuActions): boolean {
    return !!(addTileOptions?.length || onStartRename || onRemove || onChangeGroupDisplay || onCopyToDashboard)
}

interface TileGroupMenuRows {
    labels: (typeof TILE_GROUP_MENU_ITEMS)[TileGroupDisplay]
    savingReason: string | undefined
    removeDisabledReason: string | undefined
    copyDestinations: DashboardWidgetPlacementDestination[]
    onSelectCopyDestination: (dashboard: DashboardBasicType) => void
    separatorAfterAdd: boolean
    separatorAfterEdit: boolean
    separatorAfterCopy: boolean
}

export function useTileGroupMenuRows({
    groupDisplay,
    onStartRename,
    onRemove,
    groupHasTiles,
    onChangeGroupDisplay,
    copyToDestinations,
    onCopyToDashboard,
    copyLoading,
}: DashboardTileGroupMenuActions): TileGroupMenuRows {
    // Each rename sends every group, so a second rename before the first saves would undo it.
    const { dashboardLoading: dashboardSaving } = useValues(dashboardsModel)
    const labels = TILE_GROUP_MENU_ITEMS[groupDisplay]
    const savingReason = dashboardSaving ? 'Saving dashboard changes' : undefined
    const hasEditItems = !!onStartRename || !!onRemove
    const hasTrailingItems = !!onCopyToDashboard || !!onChangeGroupDisplay

    return {
        labels,
        savingReason,
        removeDisabledReason:
            savingReason ?? (groupHasTiles ? `Move this ${labels.copyNoun}'s tiles out before deleting it` : undefined),
        copyDestinations: (copyToDestinations ?? []).map((destination) =>
            copyLoading ? { ...destination, disabledReason: `Copying ${labels.copyNoun}` } : destination
        ),
        onSelectCopyDestination: ({ id, name }) => onCopyToDashboard?.(id, name || 'Untitled'),
        separatorAfterAdd: hasEditItems || hasTrailingItems,
        separatorAfterEdit: hasEditItems && hasTrailingItems,
        separatorAfterCopy: !!onCopyToDashboard && !!onChangeGroupDisplay,
    }
}

export function DashboardTileGroupMenuOverlay(actions: DashboardTileGroupMenuActions): JSX.Element {
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

    return (
        <div className="min-w-48 p-1">
            {!!addTileOptions?.length && (
                <>
                    <LemonMenu
                        placement="right-start"
                        items={addTileOptions.map((option) => ({
                            label: option.label,
                            onClick: option.onClick,
                            'data-attr': `dashboard-tile-group-menu-add-${option.key}`,
                        }))}
                    >
                        <LemonButton
                            fullWidth
                            sideIcon={<IconChevronRight />}
                            data-attr="dashboard-tile-group-menu-add"
                        >
                            Add tile
                        </LemonButton>
                    </LemonMenu>
                    {separatorAfterAdd && <LemonDivider />}
                </>
            )}
            {onStartRename && (
                <LemonButton
                    fullWidth
                    onClick={onStartRename}
                    disabledReason={savingReason}
                    data-attr="dashboard-tile-group-menu-rename"
                >
                    {renameLabel}
                </LemonButton>
            )}
            {onRemove && (
                <LemonButton
                    fullWidth
                    status="danger"
                    onClick={onRemove}
                    disabledReason={removeDisabledReason}
                    data-attr="dashboard-tile-group-menu-remove"
                >
                    {removeLabel}
                </LemonButton>
            )}
            {separatorAfterEdit && <LemonDivider />}
            {onCopyToDashboard && (
                <>
                    <DashboardWidgetPlacementMenu
                        label={copyLabel}
                        destinations={copyDestinations}
                        onSelect={onSelectCopyDestination}
                    />
                    {separatorAfterCopy && <LemonDivider />}
                </>
            )}
            {onChangeGroupDisplay && (
                <LemonButton
                    fullWidth
                    onClick={() => onChangeGroupDisplay(switchTo)}
                    data-attr={`dashboard-tile-group-menu-group-display-${switchTo}`}
                >
                    {switchLabel}
                </LemonButton>
            )}
        </div>
    )
}
