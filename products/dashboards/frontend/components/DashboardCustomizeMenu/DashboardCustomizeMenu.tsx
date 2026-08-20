import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { DashboardGridCompaction, DashboardTileSpacing } from '~/types'

import { DASHBOARD_GRID_COMPACTION_LABELS, DASHBOARD_TILE_SPACING_LABELS } from '../../dashboardCustomization'
import { DashboardTileMovementPreview } from './DashboardTileMovementPreview'

const TILE_SPACING_OPTIONS: { value: DashboardTileSpacing; label: string }[] = [
    { value: 'tight', label: DASHBOARD_TILE_SPACING_LABELS.tight },
    { value: 'condensed', label: DASHBOARD_TILE_SPACING_LABELS.condensed },
    { value: 'standard', label: DASHBOARD_TILE_SPACING_LABELS.standard },
    { value: 'relaxed', label: DASHBOARD_TILE_SPACING_LABELS.relaxed },
    { value: 'wide', label: DASHBOARD_TILE_SPACING_LABELS.wide },
]

const GRID_COMPACTION_OPTIONS: {
    value: DashboardGridCompaction
    label: JSX.Element
}[] = [
    {
        value: 'vertical',
        label: (
            <span className="flex items-center gap-2">
                <span className="text-xs font-medium">{DASHBOARD_GRID_COMPACTION_LABELS.vertical}</span>
                <LemonTag type="success">Recommended</LemonTag>
                <DashboardTileMovementPreview mode="vertical" />
            </span>
        ),
    },
    {
        value: 'horizontal',
        label: (
            <span className="flex items-center gap-2">
                <span className="text-xs font-medium">{DASHBOARD_GRID_COMPACTION_LABELS.horizontal}</span>
                <DashboardTileMovementPreview mode="horizontal" />
            </span>
        ),
    },
    {
        value: 'stable',
        label: (
            <span className="flex items-center gap-2">
                <span className="text-xs font-medium">{DASHBOARD_GRID_COMPACTION_LABELS.stable}</span>
                <DashboardTileMovementPreview mode="stable" />
            </span>
        ),
    },
]

export function DashboardCustomizeMenu(): JSX.Element | null {
    const { dashboard, canEditDashboard } = useValues(dashboardLogic)
    const {
        changeDashboardGridCompaction,
        setDashboardTileSpacing,
        saveDashboardTileSpacing,
    } = useActions(dashboardLogic)
    const dashboardCustomizationEnabled = useFeatureFlag('DASHBOARD_CUSTOMIZATION')

    if (!dashboard || !canEditDashboard || !dashboardCustomizationEnabled) {
        return null
    }

    const tileSpacing = dashboard.customization?.tile_spacing ?? 'standard'
    const layoutCompaction = dashboard.customization?.layout_compaction ?? 'vertical'
    const setTileSpacing = (value: DashboardTileSpacing): void => {
        if (value === tileSpacing) {
            return
        }
        setDashboardTileSpacing(value)
        saveDashboardTileSpacing(value)
    }

    const setGridCompaction = (value: DashboardGridCompaction): void => {
        if (value === layoutCompaction) {
            return
        }
        changeDashboardGridCompaction(value)
    }

    return (
        <div className="space-y-2 p-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="text-xs text-muted whitespace-nowrap">Tile density</span>
                <LemonRadio<DashboardTileSpacing>
                    value={tileSpacing}
                    onChange={setTileSpacing}
                    options={TILE_SPACING_OPTIONS}
                    orientation="horizontal"
                    className="flex-1 flex-wrap gap-x-3 gap-y-1"
                    aria-label="Tile density"
                />
            </div>
            <div className="flex gap-x-3 border-t pt-2">
                <span className="pt-3 text-xs text-muted whitespace-nowrap">When you move a tile</span>
                <LemonRadio<DashboardGridCompaction>
                    value={layoutCompaction}
                    onChange={setGridCompaction}
                    options={GRID_COMPACTION_OPTIONS}
                    radioPosition="top"
                    className="flex-1"
                    aria-label="How moving a tile rearranges other tiles"
                />
            </div>
        </div>
    )
}
