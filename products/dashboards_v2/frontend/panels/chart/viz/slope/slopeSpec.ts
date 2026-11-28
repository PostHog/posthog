import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const slopeSpec: VizSpec<NoOptions> = {
    type: 'slope',
    label: 'Slope chart',
    size: { w: 8, h: 14, minW: 4, minH: 8 },
    optionsSchema: NO_OPTIONS,
}
