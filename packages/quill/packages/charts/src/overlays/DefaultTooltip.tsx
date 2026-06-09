import { useChartLayout } from '../core/chart-context'
import type { TooltipContext } from '../core/types'

const DEFAULT_TOOLTIP_BG = '#1d2330'
const DEFAULT_TOOLTIP_COLOR = '#ffffff'

export function DefaultTooltip({ label, seriesData }: TooltipContext): React.ReactElement {
    const { theme } = useChartLayout()
    return (
        <div
            className="px-3 py-2 rounded-lg shadow-lg text-[13px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: theme.tooltipBackground ?? DEFAULT_TOOLTIP_BG,
                color: theme.tooltipColor ?? DEFAULT_TOOLTIP_COLOR,
            }}
        >
            <div className="font-semibold mb-1">{label}</div>
            {seriesData.map((s) => (
                <div key={s.series.key} className="flex items-center gap-2">
                    <span
                        className="inline-block size-2 rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: s.color }}
                    />
                    <span>{s.series.label}:</span>
                    <strong>{s.value.toLocaleString()}</strong>
                </div>
            ))}
        </div>
    )
}
