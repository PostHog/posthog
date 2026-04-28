import type { TooltipContext } from '../core/types'

export function DefaultTooltip({ label, seriesData }: TooltipContext): React.ReactElement {
    return (
        <div className="bg-bg-light text-primary border border-border px-3 py-2 rounded-lg shadow-lg text-[13px]">
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
