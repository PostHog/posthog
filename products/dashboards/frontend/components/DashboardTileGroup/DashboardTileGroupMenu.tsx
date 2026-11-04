import { useActions, useValues } from 'kea'

import { DashboardWidgetPlacementMenu } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { dashboardsModel } from '~/models/dashboardsModel'
import type { TileGroupDisplay } from '~/types'

const MENU_ITEMS: Record<
    TileGroupDisplay,
    { renameLabel: string; copyLabel: string; copyNoun: string; switchTo: TileGroupDisplay; switchLabel: string }
> = {
    sections: {
        renameLabel: 'Rename group',
        copyLabel: 'Copy group to dashboard',
        copyNoun: 'group',
        switchTo: 'tabs',
        switchLabel: 'Show all groups as tabs',
    },
    tabs: {
        renameLabel: 'Rename tab',
        copyLabel: 'Copy tab to dashboard',
        copyNoun: 'tab',
        switchTo: 'sections',
        switchLabel: 'Show groups as sections',
    },
}

interface DashboardTileGroupMenuProps {
    // Set by the caller to match where this menu renders: "sections" in the group header,
    // "tabs" in the tab bar. Not read from the dashboard's actual display mode.
    groupDisplay: TileGroupDisplay
    title?: string
    onRename?: (title: string) => void
    onChangeGroupDisplay?: (groupDisplay: TileGroupDisplay) => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyToDashboard?: (dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
}

export function DashboardTileGroupMenu({
    groupDisplay,
    title,
    onRename,
    onChangeGroupDisplay,
    copyToDestinations,
    onCopyToDashboard,
    copyLoading,
}: DashboardTileGroupMenuProps): JSX.Element {
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)
    // Each rename sends every group, so a second rename before the first saves would undo it.
    const { dashboardLoading: dashboardSaving } = useValues(dashboardsModel)
    const { renameLabel, copyLabel, copyNoun, switchTo, switchLabel } = MENU_ITEMS[groupDisplay]

    const openRenameDialog = (): void => {
        if (!onRename) {
            return
        }
        LemonDialog.openForm({
            title: renameLabel,
            initialValues: { title: title ?? '' },
            content: (
                <LemonField name="title">
                    <LemonInput placeholder="Leave blank to show the tile count" maxLength={200} autoFocus />
                </LemonField>
            ),
            onSubmit: ({ title: newTitle }) => onRename(newTitle),
        })
    }

    return (
        <More
            data-attr="dashboard-tile-group-menu"
            tooltip="Group actions"
            loading={copyLoading}
            disabledReason={copyLoading ? `Copying ${copyNoun}` : undefined}
            dropdown={{ onVisibilityChange: (visible) => visible && onCopyToDashboard && loadDashboardsIfNeeded() }}
            overlay={
                <div className="min-w-48 p-1">
                    {onRename && (
                        <>
                            <LemonButton
                                fullWidth
                                onClick={openRenameDialog}
                                disabledReason={dashboardSaving ? 'Saving dashboard changes' : undefined}
                                data-attr="dashboard-tile-group-menu-rename"
                            >
                                {renameLabel}
                            </LemonButton>
                            {(onCopyToDashboard || onChangeGroupDisplay) && <LemonDivider />}
                        </>
                    )}
                    {onCopyToDashboard && (
                        <>
                            <DashboardWidgetPlacementMenu
                                label={copyLabel}
                                destinations={copyToDestinations ?? []}
                                onSelect={({ id, name }) => onCopyToDashboard(id, name || 'Untitled')}
                            />
                            {onChangeGroupDisplay && <LemonDivider />}
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
            }
        />
    )
}
