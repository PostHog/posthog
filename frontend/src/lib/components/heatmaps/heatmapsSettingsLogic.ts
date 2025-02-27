import { actions, kea, path, reducers, selectors } from 'kea'
import { CommonFilters, HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'

import { calculateViewportRange, DEFAULT_HEATMAP_FILTERS } from '../IframedToolbarBrowser/utils'
import type { heatmapsSettingsLogicType } from './heatmapsSettingsLogicType'

export const heatmapsSettingsLogic = kea<heatmapsSettingsLogicType>([
    path(['lib', 'components', 'heatmaps', 'heatmapsSettingsLogic']),
    actions({
        patchHeatmapFilters: (filters: Partial<HeatmapFilters>) => ({ filters }),
        setHeatmapColorPalette: (Palette: string | null) => ({ Palette }),
        setHeatmapFixedPositionMode: (mode: HeatmapFixedPositionMode) => ({ mode }),
        setCommonFilters: (filters: CommonFilters) => ({ filters }),
        // need to know the container width to calculate viewport accuracy
        setContainerWidth: (width: number | null) => ({ width }),
    }),
    reducers({
        // they're called common filters in the toolbar because they're shared between heatmaps and clickmaps
        // the name is continued here since they're passed down into the embedded iframe
        commonFilters: [
            { date_from: '-7d' } as CommonFilters,
            {
                setCommonFilters: (_, { filters }) => filters,
            },
        ],
        heatmapColorPalette: [
            'default' as string | null,
            {
                setHeatmapColorPalette: (_, { Palette }) => Palette,
            },
        ],
        heatmapFilters: [
            DEFAULT_HEATMAP_FILTERS,
            {
                patchHeatmapFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        heatmapFixedPositionMode: [
            'fixed' as HeatmapFixedPositionMode,
            {
                setHeatmapFixedPositionMode: (_, { mode }) => mode,
            },
        ],
        containerWidth: [0, { setContainerWidth: (_, { width }) => width }],
    }),
    selectors({
        viewportRange: [
            (s) => [s.heatmapFilters, s.containerWidth],
            (heatmapFilters, containerWidth) => {
                return containerWidth ? calculateViewportRange(heatmapFilters, containerWidth) : { min: 0, max: 1800 }
            },
        ],
        heatmapTooltipLabel: [
            (s) => [s.heatmapFilters],
            (heatmapFilters) => {
                if (heatmapFilters.aggregation === 'unique_visitors') {
                    return 'visitors'
                }
                return heatmapFilters.type + 's'
            },
        ],
    }),
])
