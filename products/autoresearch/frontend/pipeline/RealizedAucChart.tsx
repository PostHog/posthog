import { dayjs } from 'lib/dayjs'

import { RealizedAucPoint } from '../onlinePerformance'

const WIDTH = 600
const HEIGHT = 160
const Y_MIN = 0.5
const Y_MAX = 1

/** Champion realized AUC per prediction date, with its 95% interval and the holdout AUC for reference. No chart deps, like MetricSparkline. */
export function RealizedAucChart({
    points,
    holdoutAuc,
}: {
    points: RealizedAucPoint[]
    holdoutAuc: number | null
}): JSX.Element {
    const x = (index: number): number => (points.length === 1 ? WIDTH / 2 : (index * WIDTH) / (points.length - 1))
    const y = (value: number): number =>
        HEIGHT - ((Math.min(Math.max(value, Y_MIN), Y_MAX) - Y_MIN) / (Y_MAX - Y_MIN)) * HEIGHT
    const banded = points.map((point, index) => ({ ...point, index })).filter((p) => p.low != null && p.high != null)
    const band = [
        ...banded.map((p) => `${x(p.index)},${y(p.high as number)}`),
        ...[...banded].reverse().map((p) => `${x(p.index)},${y(p.low as number)}`),
    ].join(' ')
    const line = points.map((p, index) => `${x(index)},${y(p.auc)}`).join(' ')
    const latest = points[points.length - 1]

    return (
        <div className="space-y-1 max-w-4xl">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-muted">
                <span>
                    <span className="inline-block w-3 h-0.5 align-middle mr-1 bg-[var(--data-color-1)]" />
                    Realized AUC, latest {latest.auc.toFixed(2)}
                </span>
                <span>
                    <span className="inline-block w-3 h-2 align-middle mr-1 bg-[var(--data-color-1)] opacity-20" />
                    95% interval
                </span>
                {holdoutAuc != null && (
                    <span>
                        <span className="inline-block w-3 align-middle mr-1 border-t border-dashed border-current" />
                        Holdout AUC {holdoutAuc.toFixed(2)}
                    </span>
                )}
            </div>
            <div className="flex gap-2">
                <div className="flex flex-col justify-between text-xs text-muted tabular-nums h-40">
                    <span>{Y_MAX.toFixed(1)}</span>
                    <span>{Y_MIN.toFixed(1)}</span>
                </div>
                <svg
                    viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                    preserveAspectRatio="none"
                    className="flex-1 min-w-0 h-40 overflow-visible border-b border-l"
                    role="img"
                    aria-label="Realized AUC over prediction dates"
                >
                    {banded.length > 0 && <polygon points={band} className="fill-[var(--data-color-1)] opacity-20" />}
                    {holdoutAuc != null && (
                        <line
                            x1={0}
                            x2={WIDTH}
                            y1={y(holdoutAuc)}
                            y2={y(holdoutAuc)}
                            className="stroke-current text-secondary"
                            strokeDasharray="6 4"
                            vectorEffect="non-scaling-stroke"
                        />
                    )}
                    <polyline
                        points={line}
                        fill="none"
                        className="stroke-[var(--data-color-1)]"
                        strokeWidth={2}
                        vectorEffect="non-scaling-stroke"
                    />
                    {points.map((p, index) => (
                        // A zero-length line with round caps stays a round dot when the SVG stretches.
                        <line
                            key={p.date}
                            x1={x(index)}
                            x2={x(index)}
                            y1={y(p.auc)}
                            y2={y(p.auc)}
                            className="stroke-[var(--data-color-1)]"
                            strokeWidth={6}
                            strokeLinecap="round"
                            vectorEffect="non-scaling-stroke"
                        >
                            <title>
                                {dayjs(p.date).format('MMM D, YYYY')}: AUC {p.auc.toFixed(3)}
                                {p.low != null && p.high != null
                                    ? ` (95% interval ${p.low.toFixed(3)} to ${p.high.toFixed(3)})`
                                    : ''}
                            </title>
                        </line>
                    ))}
                </svg>
            </div>
            <div className="flex justify-between text-xs text-muted pl-6">
                <span>{dayjs(points[0].date).format('MMM D')}</span>
                {points.length > 1 && <span>{dayjs(latest.date).format('MMM D')}</span>}
            </div>
        </div>
    )
}
