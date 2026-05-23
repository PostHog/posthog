import type { ChartTheme, TooltipContext } from '../../core/types'

const DEFAULT_TOOLTIP_BG = '#1d2330'
const DEFAULT_TOOLTIP_COLOR = '#ffffff'

const defaultValueFormatter = (value: number): string => value.toLocaleString()

export interface PieTooltipProps<Meta = unknown> {
    ctx: TooltipContext<Meta>
    theme: ChartTheme
    valueFormatter?: (value: number) => string
}

/** Default pie tooltip — shows the hovered slice's label, value, and percentage.
 *  Mirrors the layout the SQL pie chart's `InsightTooltip` uses (value + share-of-total).
 *  Consumes the same `TooltipContext` shape every other hog-chart emits: each slice is a
 *  synthetic single-point series, so `seriesData[dataIndex]` is the hovered slice. */
export function PieTooltip<Meta = unknown>({
    ctx,
    theme,
    valueFormatter = defaultValueFormatter,
}: PieTooltipProps<Meta>): React.ReactElement | null {
    const entry = ctx.seriesData[ctx.dataIndex]
    if (!entry) {
        return null
    }
    const total = ctx.seriesData.reduce((sum, e) => sum + e.value, 0)
    const percent = total > 0 ? (entry.value / total) * 100 : 0
    return (
        <div
            className="px-3 py-2 rounded-lg shadow-lg text-[13px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: theme.tooltipBackground ?? DEFAULT_TOOLTIP_BG,
                color: theme.tooltipColor ?? DEFAULT_TOOLTIP_COLOR,
            }}
        >
            <div className="flex items-center gap-2 mb-1">
                <span
                    className="inline-block size-2 rounded-full"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: entry.color }}
                />
                <span className="font-semibold">{entry.series.label}</span>
            </div>
            <div className="flex items-baseline gap-2">
                <strong>{valueFormatter(entry.value)}</strong>
                <span className="opacity-75">({percent.toFixed(1)}%)</span>
            </div>
        </div>
    )
}
