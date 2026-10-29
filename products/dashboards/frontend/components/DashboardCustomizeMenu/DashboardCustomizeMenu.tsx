import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import type { DashboardTileSpacing, TileGroupDisplay } from '~/types'

import {
    DASHBOARD_GRID_COMPACTION_LABELS,
    DASHBOARD_TILE_SPACING_LABELS,
    getTileSpacingChoices,
    DashboardGridCompaction,
    type DashboardGridCompaction as DashboardGridCompactionType,
    TILE_GROUP_DISPLAY_LABELS,
} from '../../dashboardCustomization'
import { DashboardTileMovementPreview } from './DashboardTileMovementPreview'

const TILE_GROUP_DISPLAY_OPTIONS: { value: TileGroupDisplay; label: string }[] = [
    { value: 'sections', label: TILE_GROUP_DISPLAY_LABELS.sections },
    { value: 'tabs', label: TILE_GROUP_DISPLAY_LABELS.tabs },
]

const GRID_COMPACTION_OPTIONS: {
    value: DashboardGridCompactionType
    label: JSX.Element
}[] = [
    {
        value: DashboardGridCompaction.Vertical,
        label: (
            <span className="flex items-center gap-2">
                <span className="text-xs font-medium">
                    {DASHBOARD_GRID_COMPACTION_LABELS[DashboardGridCompaction.Vertical]}
                </span>
                <LemonTag type="success">Recommended</LemonTag>
                <DashboardTileMovementPreview mode={DashboardGridCompaction.Vertical} />
            </span>
        ),
    },
    {
        value: DashboardGridCompaction.Stable,
        label: (
            <span className="flex items-center gap-2">
                <span className="text-xs font-medium">
                    {DASHBOARD_GRID_COMPACTION_LABELS[DashboardGridCompaction.Stable]}
                </span>
                <DashboardTileMovementPreview mode={DashboardGridCompaction.Stable} />
            </span>
        ),
    },
]

export function DashboardCustomizeMenu(): JSX.Element | null {
    const {
        dashboard,
        canEditDashboard,
        currentLayoutSize,
        tileGroupSections,
        tileGroupDisplay,
        dashboardGridCompactionSaving,
    } = useValues(dashboardLogic)
    const layoutAvailable = currentLayoutSize !== 'xs'
    const { changeDashboardGridCompaction, changeDashboardTileSpacing, changeTileGroupDisplay } =
        useActions(dashboardLogic)
    if (!dashboard || !canEditDashboard) {
        return null
    }

    const tileSpacing = dashboard.customization?.tile_spacing ?? 'standard'
    const layoutCompaction = dashboard.customization?.layout_compaction ?? DashboardGridCompaction.Vertical
    return (
        <div className={layoutAvailable ? 'space-y-2 p-2' : 'w-[min(20rem,calc(100vw-2rem))] space-y-2 p-2'}>
            <div className={layoutAvailable ? 'flex flex-wrap items-center gap-x-3 gap-y-1' : 'flex flex-col gap-2'}>
                <span className="text-xs text-muted whitespace-nowrap">Tile density</span>
                <LemonRadio<DashboardTileSpacing>
                    value={tileSpacing}
                    onChange={changeDashboardTileSpacing}
                    options={getTileSpacingChoices(tileSpacing).map((value) => ({
                        value,
                        label: DASHBOARD_TILE_SPACING_LABELS[value],
                    }))}
                    orientation="horizontal"
                    className={layoutAvailable ? 'flex-1 flex-wrap gap-x-3 gap-y-1' : 'flex-wrap gap-x-3 gap-y-1'}
                    aria-label="Tile density"
                />
            </div>
            {layoutAvailable ? (
                <div className="flex gap-x-3 border-t pt-2">
                    <span className="pt-3 text-xs text-muted whitespace-nowrap">When you move a tile</span>
                    <LemonRadio<DashboardGridCompactionType>
                        value={layoutCompaction}
                        onChange={changeDashboardGridCompaction}
                        options={GRID_COMPACTION_OPTIONS.map((option) => ({
                            ...option,
                            disabledReason: dashboardGridCompactionSaving ? 'Saving your last change' : undefined,
                        }))}
                        radioPosition="top"
                        className="flex-1"
                        aria-label="How moving a tile rearranges other tiles"
                    />
                </div>
            ) : (
                <p className="border-t pt-2 text-xs text-muted">Use a larger screen to move or resize tiles.</p>
            )}
            {tileGroupSections.length > 0 && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2">
                    <span className="text-xs text-muted whitespace-nowrap">Show groups as</span>
                    <LemonRadio<TileGroupDisplay>
                        value={tileGroupDisplay}
                        onChange={changeTileGroupDisplay}
                        options={TILE_GROUP_DISPLAY_OPTIONS}
                        orientation="horizontal"
                        className="flex-1 flex-wrap gap-x-3 gap-y-1"
                        aria-label="Show groups as"
                    />
                </div>
            )}
        </div>
    )
}
