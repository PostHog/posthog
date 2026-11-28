import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const sankeySpec: VizSpec<NoOptions> = {
    type: 'sankey',
    label: 'Sankey diagram',
    size: { w: 12, h: 16, minW: 6, minH: 10 },
    optionsSchema: NO_OPTIONS,
}
