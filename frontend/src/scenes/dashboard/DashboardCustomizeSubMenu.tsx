import { useActions, useValues } from 'kea'

import { IconGridMasonry } from '@posthog/icons'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

import {
    SceneMenuBarItem,
    SceneMenuBarRadioGroup,
    SceneMenuBarRadioItem,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { DashboardTileSpacing } from '~/types'

import {
    DASHBOARD_GRID_COMPACTION_LABELS,
    DASHBOARD_TILE_SPACING_LABELS,
    DashboardGridCompaction,
} from 'products/dashboards/frontend/dashboardCustomization'

import { dashboardLogic } from './dashboardLogic'

export function DashboardCustomizeSubMenu(): JSX.Element | null {
    const { dashboard, currentLayoutSize, layoutEditMode } = useValues(dashboardLogic)
    const { setDashboardEditing, changeDashboardTileSpacing, changeDashboardGridCompaction } =
        useActions(dashboardLogic)

    if (!dashboard) {
        return null
    }
    // Phones show the dashboard as one column, so there is no layout to edit or tiles to move.
    const layoutAvailable = currentLayoutSize !== 'xs'

    return (
        <SceneMenuBarSubMenu label="Customize">
            {layoutAvailable && !layoutEditMode && (
                <>
                    <SceneMenuBarItem
                        onClick={() =>
                            setDashboardEditing(
                                { filters: true, layout: true },
                                DashboardEventSource.SceneCommonButtons
                            )
                        }
                        data-attr="dashboard-menubar-edit-layout"
                    >
                        <IconGridMasonry />
                        Edit layout
                    </SceneMenuBarItem>
                    <SceneMenuBarSeparator />
                </>
            )}
            <SceneMenuBarSubMenu label="Tile density">
                <SceneMenuBarRadioGroup
                    value={dashboard.customization?.tile_spacing ?? 'standard'}
                    onValueChange={(value: unknown) => changeDashboardTileSpacing(value as DashboardTileSpacing)}
                >
                    {(Object.keys(DASHBOARD_TILE_SPACING_LABELS) as DashboardTileSpacing[]).map((spacing) => (
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
                        {Object.values(DashboardGridCompaction).map((mode) => (
                            <SceneMenuBarRadioItem
                                key={mode}
                                value={mode}
                                data-attr={`dashboard-menubar-tile-movement-${mode}`}
                            >
                                {DASHBOARD_GRID_COMPACTION_LABELS[mode]}
                            </SceneMenuBarRadioItem>
                        ))}
                    </SceneMenuBarRadioGroup>
                </SceneMenuBarSubMenu>
            )}
        </SceneMenuBarSubMenu>
    )
}
