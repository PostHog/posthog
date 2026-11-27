import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const flameGraphSpec: VizSpec<NoOptions> = {
    type: 'flame-graph',
    label: 'Flame graph',
    size: { w: 24, h: 16, minW: 8, minH: 10 },
    optionsSchema: NO_OPTIONS,
}
