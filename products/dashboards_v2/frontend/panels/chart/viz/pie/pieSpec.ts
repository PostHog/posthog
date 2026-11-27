import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const pieSpec: VizSpec<NoOptions> = {
    type: 'pie',
    label: 'Pie chart',
    size: { w: 8, h: 14, minW: 4, minH: 8 },
    optionsSchema: NO_OPTIONS,
}
