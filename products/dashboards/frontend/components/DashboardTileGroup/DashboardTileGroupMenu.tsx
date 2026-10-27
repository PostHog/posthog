import { useActions } from 'kea'

import { DashboardWidgetPlacementMenu } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { dashboardsModel } from '~/models/dashboardsModel'
import type { TileGroupDisplay } from '~/types'

const MENU_ITEMS: Record<
    TileGroupDisplay,
    { copyLabel: string; copyNoun: string; switchTo: TileGroupDisplay; switchLabel: string }
> = {
    sections: {
        copyLabel: 'Copy group to dashboard',
        copyNoun: 'group',
        switchTo: 'tabs',
        switchLabel: 'Show all groups as tabs',
    },
    tabs: {
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
    onChangeGroupDisplay?: (groupDisplay: TileGroupDisplay) => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyToDashboard?: (dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
}

export function DashboardTileGroupMenu({
    groupDisplay,
    onChangeGroupDisplay,
    copyToDestinations,
    onCopyToDashboard,
    copyLoading,
}: DashboardTileGroupMenuProps): JSX.Element {
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)
    const { copyLabel, copyNoun, switchTo, switchLabel } = MENU_ITEMS[groupDisplay]

    return (
        <More
            data-attr="dashboard-tile-group-menu"
            tooltip="Group actions"
            loading={copyLoading}
            disabledReason={copyLoading ? `Copying ${copyNoun}` : undefined}
            dropdown={{ onVisibilityChange: (visible) => visible && onCopyToDashboard && loadDashboardsIfNeeded() }}
            overlay={
                <div className="min-w-48 p-1">
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
