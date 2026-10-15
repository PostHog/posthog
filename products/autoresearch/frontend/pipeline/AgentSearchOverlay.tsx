import { useId } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import type { AgentSearch } from '../agentSearch'

/**
 * Run bands, the best-so-far step line and the live model marker, drawn over the scatter.
 * The parent pins the x domain to [0.5, N + 0.5], so x maps linearly from `seq`.
 */
export function AgentSearchOverlay({ search }: { search: AgentSearch }): JSX.Element {
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
    const liveX = live ? xOf(live.seq) : null
    const liveY = live?.holdoutScore != null ? scales.y(live.holdoutScore) : null

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
                {liveX != null && liveY != null && (
                    <g>
                        <circle cx={liveX} cy={liveY} r={8} fill="none" stroke="var(--success)" strokeWidth={2} />
                        <text
                            x={liveX}
                            // Near the top, the run band labels take the space above the marker.
                            y={liveY - 12 < plotTop + 14 ? liveY + 20 : liveY - 12}
                            fontSize={11}
                            fontWeight={600}
                            textAnchor={liveX > plotLeft + plotWidth - 40 ? 'end' : 'middle'}
                            fill="var(--color-text-primary)"
                            stroke="var(--color-bg-surface-primary)"
                            strokeWidth={3}
                            paintOrder="stroke"
                        >
                            Live model
                        </text>
                    </g>
                )}
            </g>
        </svg>
    )
}
