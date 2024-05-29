import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { CommonFilters, HeatmapFilters } from 'lib/components/heatmaps/types'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { dateMapping } from 'lib/utils'

export enum PostHogAppToolbarEvent {
    PH_TOOLBAR_INIT = 'ph-toolbar-init',
    PH_TOOLBAR_READY = 'ph-toolbar-ready',
    PH_APP_INIT = 'ph-app-init',
    PH_HEATMAPS_CONFIG = 'ph-heatmaps-config',
    PH_PATCH_HEATMAP_FILTERS = 'ph-patch-heatmap-filters',
    PH_HEATMAPS_FIXED_POSITION_MODE = 'ph-heatmaps-fixed-position-mode',
    PH_HEATMAPS_COLOR_PALETTE = 'ph-heatmaps-color-palette',
    PH_HEATMAPS_COMMON_FILTERS = 'ph-heatmaps-common-filters',
}

export const DEFAULT_HEATMAP_FILTERS: HeatmapFilters = {
    enabled: true,
    type: 'click',
    viewportAccuracy: 0.9,
    aggregation: 'total_count',
}
export const calculateViewportRange = (
    heatmapFilters: HeatmapFilters,
    windowWidth: number
): { max: number; min: number } => {
    const viewportAccuracy = heatmapFilters.viewportAccuracy ?? 0.2
    const extraPixels = windowWidth - windowWidth * viewportAccuracy

    const minWidth = Math.max(0, windowWidth - extraPixels)
    const maxWidth = windowWidth + extraPixels

    return {
        min: Math.round(minWidth),
        max: Math.round(maxWidth),
    }
}

// some of the date options we allow in insights don't apply to heatmaps/clickmaps
// let's filter the list down
const dateItemDenyList = ['Last 180 days', 'This month', 'Previous month', 'Year to date', 'All time']

export function buildToolbarDateMenuItems(setCommonFilters: (filters: CommonFilters) => void): LemonMenuItem[] {
    return dateMapping
        .filter((dm) => dm.key !== CUSTOM_OPTION_KEY && !dateItemDenyList.includes(dm.key))
        .map((dateOption) => ({
            label: dateOption.key,
            onClick: () => setCommonFilters({ date_from: dateOption.values[0], date_to: dateOption.values[1] }),
        }))
}
