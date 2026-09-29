import { curveMonotoneX, line } from 'd3'
import { useId, useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

export function OfflineScoreTrendLines(): JSX.Element {
    const clipId = useId()
    const { labels, series, scales, dimensions } = useChartLayout()
    const paths = useMemo(
        () =>
            series.map((serie) => ({
                key: serie.key,
                color: serie.color,
                path: line<[number, number]>().curve(curveMonotoneX)(
                    serie.data.flatMap((value, index) =>
                        Number.isFinite(value) ? [[scales.x(labels[index]), scales.y(value)] as [number, number]] : []
                    )
                ),
            })),
        [labels, series, scales.x, scales.y]
    )

    return (
        <svg className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden data-attr="offline-score-lines">
            <defs>
                <clipPath id={clipId}>
                    <rect
                        x={dimensions.plotLeft}
                        y={dimensions.plotTop}
                        width={dimensions.plotWidth}
                        height={dimensions.plotHeight}
                    />
                </clipPath>
            </defs>
            <g clipPath={`url(#${clipId})`}>
                {paths.map(({ key, color, path }) => (
                    <path
                        key={key}
                        d={path || undefined}
                        fill="none"
                        stroke={color}
                        strokeWidth={2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                    />
                ))}
            </g>
        </svg>
    )
}
