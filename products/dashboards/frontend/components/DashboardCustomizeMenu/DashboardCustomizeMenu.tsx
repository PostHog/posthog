import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { DashboardTileSpacing } from '~/types'

import { DASHBOARD_TILE_SPACING_LABELS } from '../../dashboardCustomization'

const TILE_SPACING_OPTIONS: { value: DashboardTileSpacing; label: string }[] = [
    { value: 'tight', label: DASHBOARD_TILE_SPACING_LABELS.tight },
    { value: 'condensed', label: DASHBOARD_TILE_SPACING_LABELS.condensed },
    { value: 'standard', label: DASHBOARD_TILE_SPACING_LABELS.standard },
    { value: 'relaxed', label: DASHBOARD_TILE_SPACING_LABELS.relaxed },
    { value: 'wide', label: DASHBOARD_TILE_SPACING_LABELS.wide },
]

export function DashboardCustomizeMenu(): JSX.Element | null {
    const { dashboard, canEditDashboard } = useValues(dashboardLogic)
    const { setDashboardTileSpacing, saveDashboardTileSpacing } = useActions(dashboardLogic)
    const dashboardCustomizationEnabled = useFeatureFlag('DASHBOARD_CUSTOMIZATION')

    if (!dashboard || !canEditDashboard || !dashboardCustomizationEnabled) {
        return null
    }

    const tileSpacing = dashboard.customization?.tile_spacing ?? 'standard'
    const setTileSpacing = (value: DashboardTileSpacing): void => {
        if (value === tileSpacing) {
            return
        }
        setDashboardTileSpacing(value)
        saveDashboardTileSpacing(value)
    }

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 p-2">
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
    )
}
