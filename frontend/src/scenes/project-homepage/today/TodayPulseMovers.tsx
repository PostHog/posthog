import { useMemo } from 'react'

import { BarList, type Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { HighlightMoverApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { useTodayTonePalette } from './todayTone'

export function TodayPulseMovers({
    movers,
    formatValue,
}: {
    movers: HighlightMoverApi[]
    formatValue: (value: number) => string
}): JSX.Element {
    const theme = useChartTheme()
    const palette = useTodayTonePalette()
    const series = useMemo<Series<HighlightMoverApi>[]>(
        () =>
            movers.map((mover) => ({
                key: mover.label,
                label: mover.label,
                data: [mover.value],
                color: palette.line,
                meta: mover,
            })),
        [movers, palette]
    )
    if (movers.some((mover) => mover.value < 0)) {
        return (
            <ul className="m-0 flex list-none flex-col gap-1 p-0" data-attr="today-pulse-card-movers">
                {series.map((row) => (
                    <li key={row.key} className="flex min-w-0 items-baseline justify-between gap-3 text-xs">
                        <span className="flex min-w-0 items-baseline gap-1.5">
                            <span className="truncate">{row.label}</span>
                            <span className="shrink-0 text-muted-foreground">
                                <TodayChange change={row.meta?.change_pct ?? null} tone="neutral" />
                            </span>
                        </span>
                        <span className="shrink-0 text-muted-foreground tabular-nums">{formatValue(row.data[0])}</span>
                    </li>
                ))}
            </ul>
        )
    }
    return (
        <BarList
            series={series}
            theme={theme}
            config={{ valueDisplay: 'value', tooltip: { enabled: false } }}
            valueFormatter={formatValue}
            renderLabel={(row) => (
                <span className="flex min-w-0 items-baseline gap-1.5">
                    <span className="truncate">{row.label}</span>
                    {row.meta && (
                        <span className="shrink-0 text-xs text-muted-foreground">
                            <TodayChange change={row.meta.change_pct} tone="neutral" />
                        </span>
                    )}
                </span>
            )}
            dataAttr="today-pulse-card-movers"
        />
    )
}
