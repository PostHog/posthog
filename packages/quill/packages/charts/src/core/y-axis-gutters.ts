import { measureLabelWidth } from '../utils/text-measure'
import { GUTTER_GAP, Y_AXIS_TITLE_MARGIN } from './hooks/useChartMargins'
import { autoFormatterFor } from './scales'
import { DEFAULT_Y_AXIS_ID } from './types'
import type { ChartScales } from './types'

/** One stacked value-axis gutter. `offset` is its outward pixel distance from the plot edge; the
 *  next gutter out clears this one's `width` + {@link GUTTER_GAP}, plus a title band when titled. */
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
    /** `scales.yTicks()` — used for the single-axis path. */
    yTicks: number[]
    yTickFormatter?: (value: number) => string
    /** Like `yTickFormatter` but only the multi-axis path consults it; the single-axis path already
     *  resolves the user formatter into `yTickFormatter`. */
    userYTickFormatter?: (value: number) => string
    yAxisFormatters?: Record<string, (value: number) => string>
    titles?: Record<string, string>
}

/** Gap from the plot edge to a gutter's tick labels — shared by AxisLabels and AxisTitles. */
export const TICK_GAP = 8

function widestTickWidth(ticks: number[], formatter: (value: number) => string): number {
    return ticks.reduce((widest, tick) => Math.max(widest, measureLabelWidth(formatter(tick))), 0)
}

/** Resolve the stacked value-axis gutters, outermost-last per side — one per axis when `scales.yAxes`
 *  is present (`showMultipleYAxes`), else a single left gutter. Shared by `AxisLabels` (ticks) and
 *  `AxisTitles` (titles) so the two can't drift. */
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
        gutters.push({
            axisId,
            key: `y-${axisId}`,
            side: axis.position,
            offset,
            width,
            title,
            ticks,
            scale: axis.scale,
            formatter,
        })
        const step = width + GUTTER_GAP + (title ? Y_AXIS_TITLE_MARGIN : 0)
        if (axis.position === 'left') {
            leftCum += step
        } else {
            rightCum += step
        }
    }
    return gutters
}
