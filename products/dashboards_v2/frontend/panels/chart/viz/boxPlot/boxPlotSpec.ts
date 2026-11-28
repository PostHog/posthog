import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const boxPlotSpec: VizSpec<NoOptions> = {
    type: 'box-plot',
    label: 'Box plot',
    size: { w: 12, h: 14, minW: 4, minH: 8 },
    optionsSchema: NO_OPTIONS,
}
