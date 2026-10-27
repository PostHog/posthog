import { useActions } from 'kea'

import { DashboardWidgetPlacementMenu } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { dashboardsModel } from '~/models/dashboardsModel'
import type { TileGroupDisplay } from '~/types'

const MENU_ITEMS: Record<TileGroupDisplay, { copyLabel: string; switchTo: TileGroupDisplay; switchLabel: string }> = {
    sections: { copyLabel: 'Copy group to dashboard', switchTo: 'tabs', switchLabel: 'Show all groups as tabs' },
    tabs: { copyLabel: 'Copy tab to dashboard', switchTo: 'sections', switchLabel: 'Show groups as sections' },
}

interface DashboardTileGroupMenuProps {
    groupDisplay: TileGroupDisplay
    onChangeGroupDisplay: (groupDisplay: TileGroupDisplay) => void
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
    const { copyLabel, switchTo, switchLabel } = MENU_ITEMS[groupDisplay]

    return (
        <More
            data-attr="dashboard-tile-group-menu"
            tooltip="Group actions"
            loading={copyLoading}
            disabledReason={copyLoading ? 'Copying group' : undefined}
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
                            <LemonDivider />
                        </>
                    )}
                    <LemonButton
                        fullWidth
                        onClick={() => onChangeGroupDisplay(switchTo)}
                        data-attr={`dashboard-tile-group-menu-group-display-${switchTo}`}
                    >
                        {switchLabel}
                    </LemonButton>
                </div>
            }
        />
    )
}
