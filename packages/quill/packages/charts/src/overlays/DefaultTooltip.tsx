import type { TooltipContext } from '../core/types'
import { TooltipSurface, TooltipSwatch } from './TooltipSurface'

export function DefaultTooltip({ label, seriesData }: TooltipContext): React.ReactElement {
    return (
        <TooltipSurface>
            <div className="font-semibold mb-1">{label}</div>
            {seriesData.map((s) => (
                <div key={s.series.key} className="flex items-center gap-2">
                    <TooltipSwatch color={s.color} />
                    <span>{s.series.label}:</span>
                    <strong>{s.value.toLocaleString()}</strong>
                </div>
            ))}
        </TooltipSurface>
    )
}
