import type { PieTooltipContext } from './PieChart'

const DEFAULT_TOOLTIP_BG = '#1d2330'
const DEFAULT_TOOLTIP_COLOR = '#ffffff'

export interface PieTooltipProps<Meta = unknown> {
    ctx: PieTooltipContext<Meta>
}

/** Default pie tooltip — shows the hovered slice's label, value, and percentage.
 *  Mirrors the layout the SQL pie chart's `InsightTooltip` uses (value + share-of-total). */
export function PieTooltip<Meta = unknown>({ ctx }: PieTooltipProps<Meta>): React.ReactElement {
    const { slice, percent, theme, valueFormatter } = ctx
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
                    style={{ backgroundColor: slice.color }}
                />
                <span className="font-semibold">{slice.label}</span>
            </div>
            <div className="flex items-baseline gap-2">
                <strong>{valueFormatter(slice.value)}</strong>
                <span className="opacity-75">({percent.toFixed(1)}%)</span>
            </div>
        </div>
    )
}
