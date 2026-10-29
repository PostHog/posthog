import { useId } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import type { AgentSearch } from '../agentSearch'

/** A ring around one point with a label above it, or below it near the top where the run band labels sit. */
function PointMarker({
    x,
    y,
    label,
    plotTop,
    plotRight,
    color,
}: {
    x: number
    y: number
    label: string
    plotTop: number
    plotRight: number
    color: string
}): JSX.Element {
    return (
        <g>
            <circle cx={x} cy={y} r={8} fill="none" stroke={color} strokeWidth={2} />
            <text
                x={x}
                y={y - 12 < plotTop + 14 ? y + 20 : y - 12}
                fontSize={11}
                fontWeight={600}
                textAnchor={x > plotRight - 60 ? 'end' : 'middle'}
                fill="var(--color-text-primary)"
                stroke="var(--color-bg-surface-primary)"
                strokeWidth={3}
                paintOrder="stroke"
            >
                {label}
            </text>
        </g>
    )
}

/**
 * Run bands, the best-so-far step line, the live model's realized AUC, and the live and scored-alongside markers, drawn over the scatter.
 * The parent pins the x domain to [0.5, N + 0.5], so x maps linearly from `seq`.
 */
export function AgentSearchOverlay({
    search,
    liveRealized,
}: {
    search: AgentSearch
    liveRealized: number | null
}): JSX.Element {
    const clipId = useId()
    const { dimensions, scales } = useChartLayout()
    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const count = search.points.length
    const xOf = (seq: number): number => plotLeft + ((seq - 0.5) / count) * plotWidth

    const segments: string[] = []
    let previous: number | null = null
    for (const point of search.points) {
        if (point.bestSoFar == null) {
            continue
        }
        const y = scales.y(point.bestSoFar)
        const left = xOf(point.seq - 0.5)
        const right = xOf(point.seq + 0.5)
        segments.push(previous == null ? `M${left},${y}` : `V${y}`, `H${right}`)
        previous = y
    }
    const stepPath = segments.join(' ')

    const live = search.points.find((p) => p.isLiveModel && p.holdoutScore != null)
    const alongside = search.points.find((p) => p.isScoredAlongside && p.holdoutScore != null)
    const realizedY = liveRealized != null ? scales.y(liveRealized) : null
    const plotRight = plotLeft + plotWidth

    return (
        <svg
            className="absolute inset-0 w-full h-full pointer-events-none"
            aria-hidden
            data-attr="autoresearch-search-overlay"
        >
            <defs>
                <clipPath id={clipId}>
                    <rect x={plotLeft} y={plotTop - 16} width={plotWidth} height={plotHeight + 16} />
                </clipPath>
            </defs>
            <g clipPath={`url(#${clipId})`}>
                {search.runs.map((run) => {
                    const left = xOf(run.firstSeq - 0.5)
                    const right = xOf(run.lastSeq + 0.5)
                    return (
                        <g key={run.runId}>
                            {run.runNumber % 2 === 0 && (
                                <rect
                                    x={left}
                                    y={plotTop}
                                    width={right - left}
                                    height={plotHeight}
                                    fill="var(--color-bg-fill-highlight-50)"
                                />
                            )}
                            {run.runNumber > 1 && (
                                <line
                                    x1={left}
                                    x2={left}
                                    y1={plotTop}
                                    y2={plotTop + plotHeight}
                                    stroke="var(--color-border-primary)"
                                    strokeDasharray="2 3"
                                />
                            )}
                            {right - left >= 56 && (
                                <text x={left + 4} y={plotTop - 4} fontSize={10} fill="var(--color-text-secondary)">
                                    {`Run ${run.runNumber} · ${dayjs(run.startedAt).format('MMM D')}`}
                                </text>
                            )}
                        </g>
                    )
                })}
                <path d={stepPath} fill="none" stroke="var(--success)" strokeWidth={1.5} strokeOpacity={0.8} />
                {realizedY != null && (
                    <g data-attr="autoresearch-search-overlay-realized">
                        <line
                            x1={plotLeft}
                            x2={plotRight}
                            y1={realizedY}
                            y2={realizedY}
                            stroke="var(--color-text-secondary)"
                            strokeWidth={1.5}
                            strokeDasharray="6 4"
                        />
                        <text
                            x={plotLeft + 4}
                            y={realizedY + 12}
                            fontSize={10}
                            textAnchor="start"
                            fill="var(--color-text-secondary)"
                            stroke="var(--color-bg-surface-primary)"
                            strokeWidth={3}
                            paintOrder="stroke"
                        >
                            {`Live model on real outcomes · ${liveRealized?.toFixed(3)}`}
                        </text>
                    </g>
                )}
                {alongside?.holdoutScore != null && (
                    <PointMarker
                        x={xOf(alongside.seq)}
                        y={scales.y(alongside.holdoutScore)}
                        label="Scored alongside"
                        plotTop={plotTop}
                        plotRight={plotRight}
                        color="var(--color-text-secondary)"
                    />
                )}
                {live?.holdoutScore != null && (
                    <PointMarker
                        x={xOf(live.seq)}
                        y={scales.y(live.holdoutScore)}
                        label="Live model"
                        plotTop={plotTop}
                        plotRight={plotRight}
                        color="var(--success)"
                    />
                )}
            </g>
        </svg>
    )
}
