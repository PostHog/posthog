import type { TooltipContext } from '../core/types'
import { formatTooltipValue } from '../core/tooltipFormat'
import { TooltipSurface, TooltipSwatch } from './TooltipSurface'

export function DefaultTooltip(ctx: TooltipContext): React.ReactElement {
    const { label, seriesData, formatValue, renderFooter } = ctx
    const format = formatValue ?? ((value: number): string => formatTooltipValue(value))
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
            {renderFooter?.(ctx)}
        </TooltipSurface>
    )
}
