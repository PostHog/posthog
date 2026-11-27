import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const comboSpec: VizSpec<NoOptions> = {
    type: 'combo',
    label: 'Bar and line chart',
    size: { w: 12, h: 16, minW: 4, minH: 8, stackedRows: { min: 10, max: 16 } },
    optionsSchema: NO_OPTIONS,
}
