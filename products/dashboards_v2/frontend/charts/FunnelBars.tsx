import {
    BarChart,
    FunnelChart,
    MAX_CATEGORY_LABEL_WIDTH,
    TooltipSurface,
    TooltipSwatch,
    ValueLabels,
    useChartLayout,
    type ChartTheme,
    type TooltipContext,
} from '@posthog/quill-charts'

import { short } from './format'

type Series = { key: string; label: string; data: number[]; color?: string }

export function funnelPercents(data: number[], from: 'first' | 'previous' = 'first'): number[] {
    const first = data[0] ?? 0
    return data.map((v, i) => {
        const base = from === 'previous' && i > 0 ? (data[i - 1] ?? 0) : first
        return base > 0 && Number.isFinite(v) ? (v / base) * 100 : 0
    })
}

const pct = (v: number): string => `${parseFloat(v.toFixed(1))}%`

export function FunnelBars({
    labels,
    series,
    theme,
    format,
    stepReference = 'first',
    horizontal,
    onStep,
}: {
    labels: string[]
    series: Series[]
    theme: ChartTheme
    format: (v: number) => string
    stepReference?: 'first' | 'previous'
    horizontal?: boolean
    onStep?: (seriesIndex: number, stepIndex: number, dropoff: boolean) => void
}): React.JSX.Element {
    const single = series.length === 1 ? series[0]! : undefined
    const shares = series.map((s) => ({ ...s, data: funnelPercents(s.data, stepReference) }))
    const tooltip = (ctx: TooltipContext): React.JSX.Element => (
        <TooltipSurface>
            <div className="mb-1 font-semibold opacity-60">{labels[ctx.dataIndex]}</div>
            <div className="grid grid-cols-[auto_1fr_auto_auto_auto] items-center gap-x-2 gap-y-0.5 tabular-nums">
                {series.map((s, si) => {
                    const n = s.data[ctx.dataIndex] ?? 0,
                        i = ctx.dataIndex
                    return [
                        <TooltipSwatch
                            key={`${si}c`}
                            color={ctx.seriesData.find((d) => d.series.key === s.key)?.color ?? s.color ?? ''}
                        />,
                        <span key={`${si}l`} className="truncate">
                            {s.label}
                        </span>,
                        <strong key={`${si}n`} className="text-right">
                            {format(n)}
                        </strong>,
                        <span key={`${si}f`} className="text-right opacity-70" title="of the first step">
                            {pct(funnelPercents(s.data)[i]!)}
                        </span>,
                        <span key={`${si}p`} className="text-right opacity-70" title="from the step before">
                            {i ? `→ ${pct(funnelPercents(s.data, 'previous')[i]!)}` : ''}
                        </span>,
                    ]
                })}
            </div>
        </TooltipSurface>
    )
    if (horizontal) {
        return (
            <BarChart
                className="min-h-0 flex-1"
                theme={theme}
                labels={labels}
                series={shares}
                tooltip={tooltip}
                onPointClick={onStep ? (((d: any) => onStep(d.seriesIndex, d.dataIndex, false)) as never) : undefined}
                config={
                    {
                        axisOrientation: 'horizontal',
                        barLayout: 'grouped',
                        bars: { track: true, fitToHeight: true, valuePadding: 120 },
                        maxCategoryLabelWidth: MAX_CATEGORY_LABEL_WIDTH,
                        showGrid: true,
                        yTickFormatter: (v: number) => `${Math.round(v)}%`,
                        valueDomain: { min: 0, max: 100 },
                        legend: { show: series.length > 1, position: 'bottom' },
                    } as never
                }
            >
                <ValueLabels
                    background={false}
                    valueFormatter={(v, si, di) => `${pct(v)} · ${format(series[si]?.data[di] ?? 0)}`}
                />
            </BarChart>
        )
    }
    return (
        <FunnelChart
            className="min-h-0 flex-1"
            theme={theme}
            steps={labels}
            series={shares}
            tooltip={tooltip}
            onStepClick={onStep ? (d) => onStep(d.seriesIndex, d.stepIndex, !d.converted) : undefined}
            config={{ legend: { show: series.length > 1, position: 'bottom' }, stepFooterAlign: 'center' }}
            stepFooter={(i) => (
                <div className="truncate px-1 pt-1 text-center text-xs leading-tight">
                    <div className="truncate font-medium" title={labels[i]}>
                        {labels[i]}
                    </div>
                    {single && <div className="text-muted-foreground tabular-nums">{format(single.data[i] ?? 0)}</div>}
                </div>
            )}
        >
            <ValueLabels valueFormatter={(v) => pct(v)} />
            {single && <StepConversions counts={single.data} heights={shares[0]!.data} />}
        </FunnelChart>
    )
}

function StepConversions({ counts, heights }: { counts: number[]; heights: number[] }): React.JSX.Element {
    const { scales, labels } = useChartLayout()
    const share = heights
    return (
        <>
            {labels.slice(1).map((l, k) => {
                const i = k + 1
                const prev = labels[i - 1]!
                const right = (scales.x(prev) ?? 0) + (scales.extent?.(prev) ?? 0) / 2
                const left = (scales.x(l) ?? 0) - (scales.extent?.(l) ?? 0) / 2
                const before = counts[i - 1] ?? 0,
                    now = counts[i] ?? 0
                return (
                    <div
                        key={l}
                        className="pointer-events-none absolute z-10 -translate-x-1/2 rounded border border-border bg-background px-1.5 py-0.5 text-center text-xs leading-tight shadow-sm tabular-nums"
                        style={{ left: (right + left) / 2, top: scales.y(share[i - 1]!) + 4 }}
                    >
                        <div className="font-semibold">→ {before > 0 ? pct((now / before) * 100) : '–'}</div>
                        {before > now && <div className="text-destructive-foreground">−{short(before - now)}</div>}
                    </div>
                )
            })}
        </>
    )
}
