import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import type { DisplayOptionTab } from 'lib/components/ChartOptions/displayOptions'
import type { ExportButtonCopyToClipboardItem, ExportButtonItem } from 'lib/components/ExportButton/ExportButton'
import type { Dayjs } from 'lib/dayjs'
import type { LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import type { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import type { DashboardBasicType, DashboardType, InsightColor } from '~/types'

import type { TileGroupMoveOptions } from 'products/dashboards/frontend/dashboardTileSections'

export interface InsightCardMenuPlacement {
    destinations: DashboardWidgetPlacementDestination[]
    onMoveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    onCopyToDashboard?: (dashboard: DashboardBasicType) => void
    tileGroupMoveOptions?: TileGroupMoveOptions
    onMoveToTileGroup?: (sectionKey: string | null) => void
}

export interface InsightCardMenu {
    view: { url: string; onCopyLink: () => void; copyLinkDataAttr: string } | null
    edit: { url: string; overrideWarning: Pick<LemonButtonProps, 'icon' | 'tooltip'> } | null
    rename: (() => void) | null
    setOverride: (() => void) | null
    duplicate: { onClick: () => void; dataAttr: string } | null
    openAlerts: (() => void) | null
    displayOptions: { visualizationItems: LemonMenuItems; tabs: DisplayOptionTab[] } | null
    /** Copy to another dashboard, for someone who cannot edit this one. */
    viewerPlacement: InsightCardMenuPlacement | null
    dashboard: {
        description: { shown: boolean; toggle: () => void } | null
        color: { current: InsightColor; update: (color: InsightColor) => void } | null
        placement: (InsightCardMenuPlacement & { removeFromDashboard?: () => void }) | null
    } | null
    deleteInsight: (() => void) | null
    export: { items: ExportButtonItem[]; copyToClipboardItems?: ExportButtonCopyToClipboardItem[] } | null
    copyImage: { onClick: () => void; disabledReason?: string }
    refresh: { onRefresh: () => void; disabledReason?: string; lastRefresh?: string | number | Dayjs | null } | null
}
