import { NO_OPTIONS, type NoOptions, type VizSpec } from '../../vizTypes'

export const areaSpec: VizSpec<NoOptions> = {
    type: 'area',
    label: 'Area chart',
    size: { w: 12, h: 16, minW: 4, minH: 8, stackedRows: { min: 10, max: 16 } },
    optionsSchema: NO_OPTIONS,
}
