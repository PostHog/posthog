import type { TooltipContext } from '../core/types'
import { TooltipSurface, TooltipSwatch } from './TooltipSurface'

interface DefaultTooltipProps extends TooltipContext {
    /** Formats each row's value. Defaults to `toLocaleString` — pass the chart's own
     *  `valueFormatter` so the tooltip matches the axis/label units (e.g. durations, currency). */
    valueFormatter?: (value: number) => string
}

export function DefaultTooltip({ label, seriesData, valueFormatter }: DefaultTooltipProps): React.ReactElement {
    const format = valueFormatter ?? ((value: number): string => value.toLocaleString())
    return (
        <TooltipSurface>
            <div className="font-semibold mb-1">{label}</div>
            {seriesData.map((s) => (
                <div key={s.series.key} className="flex items-center gap-2">
                    <TooltipSwatch color={s.color} />
                    <span>{s.series.label}:</span>
                    <strong>{format(s.value)}</strong>
                </div>
            ))}
        </TooltipSurface>
    )
}
