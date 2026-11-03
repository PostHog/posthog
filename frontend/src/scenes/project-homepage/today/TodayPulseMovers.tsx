import type { HighlightMoverApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'

export function TodayPulseMovers({ movers }: { movers: HighlightMoverApi[] }): JSX.Element {
    return (
        <ul className="m-0 flex list-none flex-col p-0" data-attr="today-pulse-card-movers">
            {movers.map((mover) => (
                <li key={mover.label} className="flex min-w-0 items-baseline justify-between gap-3 py-1 text-xs">
                    <span className="truncate">{mover.label}</span>
                    <span className="shrink-0 text-muted-foreground tabular-nums">
                        <TodayChange change={mover.change_pct} tone="neutral" />
                    </span>
                </li>
            ))}
        </ul>
    )
}
