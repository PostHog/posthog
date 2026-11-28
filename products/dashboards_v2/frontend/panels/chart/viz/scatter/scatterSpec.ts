import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const scatterSpec: VizSpec<NoOptions> = {
    type: 'scatter',
    label: 'Scatter plot',
    // Six columns leave the plot room between the axis labels, so its points don't pile up.
    size: { w: 12, h: 14, minW: 6, minH: 8 },
    optionsSchema: NO_OPTIONS,
}
