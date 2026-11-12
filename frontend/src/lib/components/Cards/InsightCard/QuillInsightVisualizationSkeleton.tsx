import { Skeleton, cn } from '@posthog/quill'

import { InsightModel } from '~/types'

import { visualizationShape } from './visualizationShape'

const BAR_HEIGHTS = ['h-2/5', 'h-3/5', 'h-1/2', 'h-4/5', 'h-2/3', 'h-3/4', 'h-1/3', 'h-3/5']
const FUNNEL_WIDTHS = ['w-full', 'w-4/5', 'w-3/5', 'w-2/5']
// The shapes an SVG has to draw take the pulse and the 12% foreground fill of quill's Skeleton.
// The opacity is an SVG attribute because the app has no opacity variants of quill's color classes.
const DRAWN_SHAPE_CLASS = 'animate-pulse text-foreground motion-reduce:animate-none'
const DRAWN_SHAPE_OPACITY = 0.12
const PIE_SIZE_CLASS = 'aspect-square h-28 max-h-full shrink-0'

export function QuillInsightVisualizationSkeleton({
    query,
    className,
}: {
    query?: InsightModel['query']
    className?: string
}): JSX.Element {
    const shape = query ? visualizationShape(query) : 'line'

    let chart: JSX.Element
    if (shape === 'number') {
        chart = (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4">
                <Skeleton className="h-12 w-1/3" />
                <Skeleton className="h-3 w-1/4" />
            </div>
        )
    } else if (shape === 'pie' || shape === 'donut') {
        chart = (
            <div className="flex min-h-0 flex-1 flex-wrap items-center justify-center gap-4">
                {shape === 'donut' ? (
                    <svg viewBox="0 0 100 100" className={cn(PIE_SIZE_CLASS, DRAWN_SHAPE_CLASS)}>
                        <circle
                            cx="50"
                            cy="50"
                            r="36"
                            fill="none"
                            stroke="currentColor"
                            strokeOpacity={DRAWN_SHAPE_OPACITY}
                            strokeWidth="28"
                        />
                    </svg>
                ) : (
                    <Skeleton className={cn(PIE_SIZE_CLASS, 'rounded-full')} />
                )}
                <div className="flex flex-col gap-4">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="h-3 w-20" />
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
                            <Skeleton key={columnIndex} className="h-full flex-1" />
                        ))}
                    </div>
                ))}
            </div>
        )
    } else if (shape === 'funnel') {
        chart = (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4">
                {FUNNEL_WIDTHS.map((widthClass) => (
                    <Skeleton key={widthClass} className={cn('h-9', widthClass)} />
                ))}
            </div>
        )
    } else {
        chart = (
            <>
                <div className="relative min-h-0 flex-1 border-b border-l border-border">
                    {/* Out of the flow, so the plot takes the height it is given and the bar heights resolve against it. */}
                    <div className="absolute inset-3 flex items-end gap-2">
                        {shape === 'bar' ? (
                            BAR_HEIGHTS.map((heightClass, index) => (
                                <Skeleton key={index} className={cn('flex-1', heightClass)} />
                            ))
                        ) : (
                            <svg
                                viewBox="0 0 320 160"
                                preserveAspectRatio="none"
                                className={cn('size-full', DRAWN_SHAPE_CLASS)}
                            >
                                <path
                                    d="M0 125 C35 120 55 45 90 85 S135 145 175 65 S235 115 270 45 S305 70 320 20"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeOpacity={DRAWN_SHAPE_OPACITY}
                                    strokeWidth="4"
                                    vectorEffect="non-scaling-stroke"
                                />
                            </svg>
                        )}
                    </div>
                </div>
                <div className="flex justify-between gap-3">
                    {Array.from({ length: 5 }, (_, index) => (
                        <Skeleton key={index} className="h-2 w-8" />
                    ))}
                </div>
            </>
        )
    }

    return (
        <div data-quill aria-hidden="true" className={cn('flex min-h-0 flex-1 flex-col gap-3', className)}>
            {chart}
        </div>
    )
}
