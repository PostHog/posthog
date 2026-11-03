import type { HighlightMoverApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'

export function TodayPulseMovers({
    movers,
    formatValue,
}: {
    movers: HighlightMoverApi[]
    formatValue: (value: number) => string
}): JSX.Element {
    return (
        <ul className="m-0 flex list-none flex-col p-0" data-attr="today-pulse-card-movers">
            {movers.map((mover) => (
                <li key={mover.label} className="flex min-w-0 items-baseline gap-3 py-1 text-xs">
                    <span className="min-w-0 flex-1 truncate">{mover.label}</span>
                    <span className="shrink-0 tabular-nums" translate="no">
                        {formatValue(mover.value).replace(/^-/, '−')}
                    </span>
                    <span className="w-12 shrink-0 text-end text-muted-foreground tabular-nums">
                        <TodayChange change={mover.change_pct} tone="neutral" />
                    </span>
                </li>
            ))}
        </ul>
    )
}
