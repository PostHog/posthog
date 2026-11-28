import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const proportionSpec: VizSpec<NoOptions> = {
    type: 'proportion',
    label: 'Proportion bar',
    size: { w: 12, h: 6, minW: 4, minH: 4 },
    optionsSchema: NO_OPTIONS,
}
