import { normalizeAxisLabel } from '../utils/axis-labels'
import { DEFAULT_Y_AXIS_ID } from './types'
import type { YAxis } from './types'

/** Per-axis y-axis titles keyed by axis id. */
export type YAxisTitles = Record<string, string>

/** Resolve per-axis titles from `yAxes`, falling back to the scalar `yAxisLabel` as one left axis.
 *  Only axes with a non-blank label appear in the map. */
export function resolveYAxisTitles(yAxes: YAxis[] | undefined, yAxisLabel: string | undefined): YAxisTitles {
    const axes: YAxis[] = yAxes ?? [{ id: DEFAULT_Y_AXIS_ID, position: 'left', label: yAxisLabel }]
    const titles: YAxisTitles = {}
    for (const axis of axes) {
        const label = normalizeAxisLabel(axis.label)
        if (label) {
            titles[axis.id] = label
        }
    }
    return titles
}
