import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { DashboardTileSpacing, TileGroupDisplay } from '~/types'

import {
    DASHBOARD_GRID_COMPACTION_LABELS,
    DASHBOARD_TILE_SPACING_LABELS,
    DashboardGridCompaction,
    TILE_GROUP_DISPLAY_LABELS,
    getTileSpacingChoices,
} from 'products/dashboards/frontend/dashboardCustomization'

/** The "Customize" submenu: tile density, how tiles move, and how groups show. Empty without a dashboard. */
export function useDashboardCustomizeAction(): SceneAction[] {
    const { dashboard, currentLayoutSize, tileGroupSections, tileGroupDisplay, dashboardGridCompactionSaving } =
        useValues(dashboardLogic)
    const { changeDashboardTileSpacing, changeDashboardGridCompaction, changeTileGroupDisplay } =
        useActions(dashboardLogic)

    if (!dashboard) {
        return []
    }
    const tileSpacing = dashboard.customization?.tile_spacing ?? 'standard'
    // Phones show the dashboard as one column, so there is no layout to edit or tiles to move.
    const layoutAvailable = currentLayoutSize !== 'xs'

    return [
        {
            group: 'file',
            section: 'tiles',
            type: 'submenu',
            id: 'dashboard-menubar-customize',
            label: 'Customize',
            icon: <IconGear />,
            display: 'submenu',
            items: [
                {
                    type: 'radio',
                    // pinned: data-attr values are wire strings
                    id: 'dashboard-menubar-tile-density',
                    label: 'Tile density',
                    value: tileSpacing,
                    options: getTileSpacingChoices(tileSpacing).map((spacing) => ({
                        value: spacing,
                        label: DASHBOARD_TILE_SPACING_LABELS[spacing],
                    })),
                    onValueChange: (value) => changeDashboardTileSpacing(value as DashboardTileSpacing),
                },
                ...(layoutAvailable
                    ? [
                          {
                              type: 'radio' as const,
                              id: 'dashboard-menubar-tile-movement',
                              label: 'When you move a tile',
                              value: dashboard.customization?.layout_compaction ?? DashboardGridCompaction.Vertical,
                              options: [DashboardGridCompaction.Vertical, DashboardGridCompaction.Stable].map(
                                  (mode) => ({
                                      value: mode,
                                      label: DASHBOARD_GRID_COMPACTION_LABELS[mode],
                                      disabledReason: dashboardGridCompactionSaving ? 'Saving' : undefined,
                                  })
                              ),
                              onValueChange: (value: string) =>
                                  changeDashboardGridCompaction(value as DashboardGridCompaction),
                          },
                      ]
                    : []),
                ...(tileGroupSections.length > 0
                    ? [
                          {
                              type: 'radio' as const,
                              id: 'dashboard-menubar-group-display',
                              label: 'Show groups as',
                              value: tileGroupDisplay,
                              options: (Object.keys(TILE_GROUP_DISPLAY_LABELS) as TileGroupDisplay[]).map(
                                  (display) => ({ value: display, label: TILE_GROUP_DISPLAY_LABELS[display] })
                              ),
                              onValueChange: (value: string) => changeTileGroupDisplay(value as TileGroupDisplay),
                          },
                      ]
                    : []),
            ],
        },
    ]
}
