import clsx from 'clsx'

import { type ChartBlock, type MetricCard } from '../types'

const TREND_PATH = 'M0,55 C40,48 70,24 110,32 C150,40 175,12 220,18 C265,24 300,48 340,30 C380,16 410,22 440,10'

function MiniTrendChart(): JSX.Element {
    return (
        <svg viewBox="0 0 440 80" preserveAspectRatio="none" className="h-14 w-full">
            <path d={`${TREND_PATH} L440,80 L0,80 Z`} className="fill-accent opacity-8" />
            <path d={TREND_PATH} fill="none" className="stroke-accent" strokeWidth="2" strokeLinecap="round" />
        </svg>
    )
}

const BARS = [62, 88, 52, 78, 95, 68, 84, 58, 92]

function MiniBarChart(): JSX.Element {
    const barWidth = 160 / BARS.length
    return (
        <svg viewBox="0 0 160 80" preserveAspectRatio="none" className="h-14 w-full">
            {BARS.map((height, i) => {
                const barH = (height / 100) * 80
                return (
                    <rect
                        key={i}
                        x={i * barWidth + 2}
                        y={80 - barH}
                        width={barWidth - 4}
                        height={barH}
                        rx="1.5"
                        className="fill-accent"
                    />
                )
            })}
        </svg>
    )
}

function MetricCardView({ metric }: { metric: MetricCard }): JSX.Element {
    return (
        <div className="rounded-lg border border-primary bg-surface-primary p-3">
            <div className="text-xs text-secondary mb-1">{metric.label}</div>
            <div className="text-base font-bold text-default">{metric.value}</div>
            {metric.delta && (
                <div
                    className={clsx(
                        'mt-1 text-xs font-semibold',
                        metric.deltaPositive ? 'text-success' : 'text-danger'
                    )}
                >
                    {metric.deltaPositive ? '▲' : '▼'} {metric.delta}
                </div>
            )}
        </div>
    )
}

export function DashboardPage({ metrics, charts }: { metrics: MetricCard[]; charts?: ChartBlock[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-default">Overview</h2>
                <div className="ml-auto flex items-center gap-1 text-xs text-secondary">
                    <span className="rounded bg-surface-secondary px-1.5 py-px">Last 7 days</span>
                </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
                {metrics.map((metric) => (
                    <MetricCardView key={metric.label} metric={metric} />
                ))}
            </div>
            {charts && charts.length > 0 && (
                <div className="flex flex-col gap-2">
                    {charts.map((chart, i) => (
                        <div key={i} className="rounded-lg border border-primary bg-surface-primary p-3">
                            <div className="text-xs text-secondary mb-1.5">{chart.title}</div>
                            {chart.kind === 'trend' && <MiniTrendChart />}
                            {chart.kind === 'bars' && <MiniBarChart />}
                            {chart.kind === 'table' &&
                                chart.rows?.map((row, ri) => (
                                    <div
                                        key={ri}
                                        className={clsx(
                                            'flex items-center justify-between py-1 text-xs',
                                            ri < (chart.rows?.length ?? 0) - 1 && 'border-b border-primary'
                                        )}
                                    >
                                        <span className="text-secondary">{row.label}</span>
                                        <span className="text-default tabular-nums">{row.value}</span>
                                    </div>
                                ))}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
