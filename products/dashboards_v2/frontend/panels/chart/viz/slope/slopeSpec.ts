import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const slopeSpec: VizSpec<NoOptions> = {
    type: 'slope',
    label: 'Slope chart',
    // Labels sit on both ends of each line, so six columns keep the lines long enough to read and every label shown.
    size: { w: 8, h: 14, minW: 6, minH: 8 },
    optionsSchema: NO_OPTIONS,
}
