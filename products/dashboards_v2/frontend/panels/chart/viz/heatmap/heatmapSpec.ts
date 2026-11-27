import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const heatmapSpec: VizSpec<NoOptions> = {
    type: 'heatmap',
    label: 'Heatmap',
    size: { w: 12, h: 14, minW: 6, minH: 8 },
    optionsSchema: NO_OPTIONS,
}
