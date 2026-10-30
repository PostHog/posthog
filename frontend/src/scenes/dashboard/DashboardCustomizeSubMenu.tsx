import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SidePanelActivityTab } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    SceneMenuBarItem,
    SceneMenuBarRadioGroup,
    SceneMenuBarRadioItem,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { DashboardTileSpacing, SidePanelTab, TileGroupDisplay } from '~/types'

import {
    DASHBOARD_GRID_COMPACTION_LABELS,
    DASHBOARD_TILE_SPACING_LABELS,
    getTileSpacingChoices,
    DashboardGridCompaction,
    TILE_GROUP_DISPLAY_LABELS,
} from 'products/dashboards/frontend/dashboardCustomization'

import { dashboardLogic } from './dashboardLogic'

export function DashboardCustomizeSubMenu(): JSX.Element | null {
    const {
        dashboard,
        currentLayoutSize,
        canEditDashboard,
        tileGroupSections,
        tileGroupDisplay,
        dashboardGridCompactionSaving,
    } = useValues(dashboardLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const layoutUndoEnabled = useFeatureFlag('DASHBOARD_LAYOUT_UNDO')
    const { changeDashboardTileSpacing, changeDashboardGridCompaction, changeTileGroupDisplay } =
        useActions(dashboardLogic)

    if (!dashboard) {
        return null
    }
    // Phones show the dashboard as one column, so there is no layout to edit or tiles to move.
    const layoutAvailable = currentLayoutSize !== 'xs'

    return (
        <SceneMenuBarSubMenu label="Customize">
            {canEditDashboard && layoutUndoEnabled && (
                <>
                    {/* Layout changes save as they happen, so earlier layouts live in the activity log. */}
                    <SceneMenuBarItem
                        onClick={() => openSidePanel(SidePanelTab.Activity, SidePanelActivityTab.All)}
                        data-attr="dashboard-menubar-layout-history"
                    >
                        <IconClock />
                        Layout history
                    </SceneMenuBarItem>
                    <SceneMenuBarSeparator />
                </>
            )}
            <SceneMenuBarSubMenu label="Tile density">
                <SceneMenuBarRadioGroup
                    value={dashboard.customization?.tile_spacing ?? 'standard'}
                    onValueChange={(value: unknown) => changeDashboardTileSpacing(value as DashboardTileSpacing)}
                >
                    {getTileSpacingChoices(dashboard.customization?.tile_spacing ?? 'standard').map((spacing) => (
                        <SceneMenuBarRadioItem
                            key={spacing}
                            value={spacing}
                            data-attr={`dashboard-menubar-tile-density-${spacing}`}
                        >
                            {DASHBOARD_TILE_SPACING_LABELS[spacing]}
                        </SceneMenuBarRadioItem>
                    ))}
                </SceneMenuBarRadioGroup>
            </SceneMenuBarSubMenu>
            {layoutAvailable && (
                <SceneMenuBarSubMenu label="When you move a tile">
                    <SceneMenuBarRadioGroup
                        value={dashboard.customization?.layout_compaction ?? DashboardGridCompaction.Vertical}
                        onValueChange={(value: unknown) =>
                            changeDashboardGridCompaction(value as DashboardGridCompaction)
                        }
                    >
                        {[DashboardGridCompaction.Vertical, DashboardGridCompaction.Stable].map((mode) => (
                            <SceneMenuBarRadioItem
                                key={mode}
                                value={mode}
                                disabled={dashboardGridCompactionSaving}
                                data-attr={`dashboard-menubar-tile-movement-${mode}`}
                            >
                                {DASHBOARD_GRID_COMPACTION_LABELS[mode]}
                            </SceneMenuBarRadioItem>
                        ))}
                    </SceneMenuBarRadioGroup>
                </SceneMenuBarSubMenu>
            )}
            {tileGroupSections.length > 0 && (
                <SceneMenuBarSubMenu label="Show groups as">
                    <SceneMenuBarRadioGroup
                        value={tileGroupDisplay}
                        onValueChange={(value: unknown) => changeTileGroupDisplay(value as TileGroupDisplay)}
                    >
                        {(Object.keys(TILE_GROUP_DISPLAY_LABELS) as TileGroupDisplay[]).map((display) => (
                            <SceneMenuBarRadioItem
                                key={display}
                                value={display}
                                data-attr={`dashboard-menubar-group-display-${display}`}
                            >
                                {TILE_GROUP_DISPLAY_LABELS[display]}
                            </SceneMenuBarRadioItem>
                        ))}
                    </SceneMenuBarRadioGroup>
                </SceneMenuBarSubMenu>
            )}
        </SceneMenuBarSubMenu>
    )
}
