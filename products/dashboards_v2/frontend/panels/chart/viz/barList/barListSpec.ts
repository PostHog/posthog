import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const barListSpec: VizSpec<NoOptions> = {
    type: 'bar-list',
    label: 'Bar list',
    size: { w: 8, h: 14, minW: 4, minH: 6 },
    optionsSchema: NO_OPTIONS,
}
