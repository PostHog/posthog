import { normalizeAxisLabel } from '../utils/axis-labels'
import { DEFAULT_Y_AXIS_ID } from './types'
import type { YAxis } from './types'

/** Resolved y-axis titles keyed by axis id. Every axis renders its own title at its gutter — there
 *  is no per-side special case. */
export type YAxisTitles = Record<string, string>

/** Resolve the per-axis y-axis titles from the resolved axis list. Multi-axis charts pass their
 *  `yAxes`; single-axis charts pass the scalar `yAxisLabel`, which normalizes to one left axis.
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
