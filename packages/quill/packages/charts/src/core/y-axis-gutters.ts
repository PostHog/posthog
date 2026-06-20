import { measureLabelWidth } from '../utils/text-measure'
import { GUTTER_GAP, Y_AXIS_TITLE_MARGIN } from './hooks/useChartMargins'
import { autoFormatterFor } from './scales'
import { DEFAULT_Y_AXIS_ID } from './types'
import type { ChartScales } from './types'

/** One value-axis gutter: which axis it belongs to, its side, the ticks/scale/formatter it draws
 *  with, the outward pixel `offset` from the plot edge to its inner edge, the `width` its widest
 *  tick label occupies, and its `title` (if any). Gutters stack outward per side; the next gutter's
 *  `offset` clears this one's `width` plus {@link GUTTER_GAP}, plus the title band when titled. */
export interface Gutter {
    axisId: string
    key: string
    side: 'left' | 'right'
    offset: number
    width: number
    title?: string
    ticks: number[]
    scale: (value: number) => number
    formatter: (value: number) => string
}

export interface YAxisGutterOptions {
    /** Default (left) axis ticks — `scales.yTicks()`. Used for the single-axis path. */
    yTicks: number[]
    /** Explicit user formatter. When set, every stacked axis uses it; otherwise each axis
     *  auto-formats against its own ticks. */
    yTickFormatter?: (value: number) => string
    /** Same as `yTickFormatter` but only the multi-axis path consults it (the single-axis path
     *  already resolves the user formatter into `yTickFormatter`). */
    userYTickFormatter?: (value: number) => string
    /** Per-axis tick formatters keyed by axis id; a gutter prefers its own, then the user
     *  formatter, then auto-formats. */
    yAxisFormatters?: Record<string, (value: number) => string>
    /** Per-axis titles keyed by axis id. A titled gutter reserves an extra title band on its side,
     *  so a stacked inner title doesn't overlap the next axis out. */
    titles?: Record<string, string>
}

function widestTickWidth(ticks: number[], formatter: (value: number) => string): number {
    return ticks.reduce((widest, tick) => Math.max(widest, measureLabelWidth(formatter(tick))), 0)
}

/** Resolve the stacked value-axis gutters, outermost-last per side. With per-axis scales
 *  (`scales.yAxes`, i.e. `showMultipleYAxes`) there is one gutter per axis, each offset by the
 *  cumulative width of the inner gutters (and their title bands); without, a single left gutter from
 *  the shared scale. Shared by `AxisLabels` (ticks), `AxisTitles` (titles), and the margin
 *  reservation so the three can't drift. */
export function computeYAxisGutters(
    scales: ChartScales,
    { yTicks, yTickFormatter, userYTickFormatter, yAxisFormatters, titles }: YAxisGutterOptions
): Gutter[] {
    if (!scales.yAxes) {
        const formatter = yTickFormatter ?? autoFormatterFor(yTicks)
        return [
            {
                axisId: DEFAULT_Y_AXIS_ID,
                key: 'y-left',
                side: 'left',
                offset: 0,
                width: widestTickWidth(yTicks, formatter),
                title: titles?.[DEFAULT_Y_AXIS_ID],
                ticks: yTicks,
                scale: scales.y,
                formatter,
            },
        ]
    }
    let leftCum = 0
    let rightCum = 0
    const gutters: Gutter[] = []
    for (const [axisId, axis] of Object.entries(scales.yAxes)) {
        const ticks = axis.ticks()
        const formatter = yAxisFormatters?.[axisId] ?? userYTickFormatter ?? autoFormatterFor(ticks)
        const offset = axis.position === 'left' ? leftCum : rightCum
        const width = widestTickWidth(ticks, formatter)
        const title = titles?.[axisId]
        gutters.push({ axisId, key: `y-${axisId}`, side: axis.position, offset, width, title, ticks, scale: axis.scale, formatter })
        const step = width + GUTTER_GAP + (title ? Y_AXIS_TITLE_MARGIN : 0)
        if (axis.position === 'left') {
            leftCum += step
        } else {
            rightCum += step
        }
    }
    return gutters
}
