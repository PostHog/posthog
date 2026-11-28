import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const funnelSpec: VizSpec<NoOptions> = {
    type: 'funnel',
    label: 'Funnel',
    size: { w: 12, h: 14, minW: 6, minH: 8 },
    optionsSchema: NO_OPTIONS,
}
