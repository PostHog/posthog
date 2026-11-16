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
        <ul
            className="m-0 grid list-none grid-cols-[minmax(0,1fr)_auto_minmax(3rem,auto)] gap-x-3 p-0"
            data-attr="today-pulse-card-movers"
        >
            {movers.map((mover) => (
                <li key={mover.label} className="col-span-3 grid grid-cols-subgrid items-baseline py-1 text-xs">
                    <span className="min-w-0 truncate">{mover.label}</span>
                    <span className="text-end tabular-nums" translate="no">
                        {formatValue(mover.value).replace(/^-/, '−')}
                    </span>
                    <span className="text-end text-muted-foreground tabular-nums">
                        <TodayChange change={mover.change_pct} tone="neutral" />
                    </span>
                </li>
            ))}
        </ul>
    )
}
