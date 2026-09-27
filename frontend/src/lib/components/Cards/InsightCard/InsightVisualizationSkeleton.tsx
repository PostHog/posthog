import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { InsightModel } from '~/types'

import { visualizationShape } from './visualizationShape'

const BAR_HEIGHTS = ['h-2/5', 'h-3/5', 'h-1/2', 'h-4/5', 'h-2/3', 'h-3/4', 'h-1/3', 'h-3/5']
const FUNNEL_WIDTHS = ['w-full', 'w-4/5', 'w-3/5', 'w-2/5']
export function InsightVisualizationSkeleton({ query }: { query: InsightModel['query'] }): JSX.Element {
    const shape = visualizationShape(query)

    let chart: JSX.Element
    if (shape === 'number') {
        chart = (
            <div className="flex flex-1 flex-col items-center justify-center gap-4">
                <LemonSkeleton className="h-12 w-1/3" active={false} />
                <LemonSkeleton className="h-3 w-1/4" active={false} />
            </div>
        )
    } else if (shape === 'pie' || shape === 'donut') {
        chart = (
            <div className="flex flex-1 flex-wrap items-center justify-center gap-4">
                <div className="relative size-28 shrink-0">
                    <svg viewBox="0 0 100 100" className="size-full">
                        <path d="M50 50 L50 0 A50 50 0 0 1 97 67 Z" fill="var(--color-skeleton-dark)" />
                        <path d="M50 50 L97 67 A50 50 0 0 1 3 67 Z" fill="var(--color-skeleton-light)" />
                        <path d="M50 50 L3 67 A50 50 0 0 1 50 0 Z" fill="var(--color-skeleton-dark)" />
                    </svg>
                    {shape === 'donut' && <div className="absolute inset-8 rounded-full bg-surface-primary" />}
                </div>
                <div className="flex flex-col gap-4">
                    <LemonSkeleton className="h-3 w-20" active={false} />
                    <LemonSkeleton className="h-3 w-16" active={false} />
                    <LemonSkeleton className="h-3 w-20" active={false} />
                </div>
            </div>
        )
    } else if (shape === 'table' || shape === 'heatmap') {
        const rowCount = shape === 'heatmap' ? 3 : 5
        const columnCount = shape === 'heatmap' ? 5 : 3
        chart = (
            <div className="flex flex-1 flex-col justify-around gap-2">
                {Array.from({ length: rowCount }, (_, rowIndex) => (
                    <div key={rowIndex} className="flex flex-1 gap-3">
                        {Array.from({ length: columnCount }, (_, columnIndex) => (
                            <LemonSkeleton key={columnIndex} className="h-full flex-1" active={false} />
                        ))}
                    </div>
                ))}
            </div>
        )
    } else if (shape === 'funnel') {
        chart = (
            <div className="flex flex-1 flex-col items-center justify-center gap-4">
                {FUNNEL_WIDTHS.map((widthClass) => (
                    <LemonSkeleton key={widthClass} className={`h-9 ${widthClass}`} active={false} />
                ))}
            </div>
        )
    } else {
        const plot =
            shape === 'bar' ? (
                BAR_HEIGHTS.map((heightClass, index) => (
                    <LemonSkeleton key={index} className={`flex-1 ${heightClass}`} active={false} />
                ))
            ) : (
                <svg viewBox="0 0 320 160" preserveAspectRatio="none" className="size-full">
                    <path
                        d="M0 125 C35 120 55 45 90 85 S135 145 175 65 S235 115 270 45 S305 70 320 20"
                        fill="none"
                        stroke="var(--color-skeleton-dark)"
                        strokeWidth="4"
                        vectorEffect="non-scaling-stroke"
                    />
                </svg>
            )
        chart = (
            <>
                <div className="flex flex-1 min-h-0 items-end gap-2 border-b border-l border-primary p-3">{plot}</div>
                <div className="flex justify-between gap-3">
                    {Array.from({ length: 5 }, (_, index) => (
                        <LemonSkeleton key={index} className="h-2 w-8" active={false} />
                    ))}
                </div>
            </>
        )
    }

    return (
        <div className="InsightCard__viz p-4" aria-hidden="true">
            <div className="flex flex-1 min-h-0 flex-col gap-3">{chart}</div>
        </div>
    )
}
