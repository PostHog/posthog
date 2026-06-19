import clsx from 'clsx'

import { type MetricCard } from '../types'

const TREND_PATH = 'M0,70 C40,62 70,34 110,40 C150,46 175,16 220,22 C265,28 300,52 340,36 C380,22 410,28 440,14'
const BARS = [54, 80, 46, 70, 90, 62, 78, 52, 86]

/** The design's MiniWorkspace: stat cards + an optional trend line + an optional bar chart. */
export function DashboardPage({
    metrics,
    showTrend,
    showBars,
}: {
    metrics: MetricCard[]
    showTrend?: boolean
    showBars?: boolean
}): JSX.Element {
    const barWidth = 200 / BARS.length
    return (
        <div className="grid grid-cols-3 gap-2">
            {metrics.map((metric) => (
                <div key={metric.label} className="rounded-lg border border-primary bg-surface-primary p-2.5">
                    <div className="text-muted text-[10px] font-semibold">{metric.label}</div>
                    <div className="mt-0.5 text-lg font-bold text-default">{metric.value}</div>
                    {metric.delta && (
                        <div
                            className={clsx(
                                'mt-0.5 text-[10px] font-bold',
                                metric.deltaPositive ? 'text-success' : 'text-danger'
                            )}
                        >
                            {metric.deltaPositive ? '▲' : '▼'} {metric.delta}
                        </div>
                    )}
                </div>
            ))}
            {showTrend && (
                <div className="col-span-3 rounded-lg border border-primary bg-surface-primary p-2.5">
                    <div className="text-muted mb-1.5 text-[10px] font-semibold">Pageviews · trends</div>
                    <svg viewBox="0 0 440 84" preserveAspectRatio="none" className="h-14 w-full">
                        <path d={`${TREND_PATH} L440,84 L0,84 Z`} className="text-accent fill-current opacity-10" />
                        <path
                            d={TREND_PATH}
                            fill="none"
                            className="text-accent stroke-current"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                        />
                    </svg>
                </div>
            )}
            {showBars && (
                <div className="col-span-3 rounded-lg border border-primary bg-surface-primary p-2.5">
                    <div className="text-muted mb-1.5 text-[10px] font-semibold">Top events</div>
                    <svg viewBox="0 0 200 64" preserveAspectRatio="none" className="h-14 w-full">
                        {BARS.map((height, i) => {
                            const barHeight = (height / 100) * 64
                            return (
                                <rect
                                    key={i}
                                    x={i * barWidth + 2}
                                    y={64 - barHeight}
                                    width={barWidth - 4}
                                    height={barHeight}
                                    rx="1.5"
                                    className="text-accent fill-current"
                                />
                            )
                        })}
                    </svg>
                </div>
            )}
        </div>
    )
}
