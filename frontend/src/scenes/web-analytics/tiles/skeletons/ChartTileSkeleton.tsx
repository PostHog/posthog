import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { range } from 'lib/utils/arrays'

export interface ChartTileSkeletonProps {
    bars?: number
    showLegendStrip?: boolean
}

const BAR_HEIGHTS_PERCENT = [40, 55, 60, 50, 70, 80, 65, 75, 90, 70, 80, 95, 85, 75, 60, 70, 55, 65, 75, 80]
const AXIS_TICK_COUNT = 6

export function ChartTileSkeleton({ bars = 14, showLegendStrip = true }: ChartTileSkeletonProps): JSX.Element {
    const heights = range(bars).map((i) => BAR_HEIGHTS_PERCENT[i % BAR_HEIGHTS_PERCENT.length])

    return (
        <div data-attr="web-analytics-skeleton-chart" className="flex flex-col flex-1 min-h-72">
            {showLegendStrip && (
                <div
                    data-attr="web-analytics-skeleton-chart-legend"
                    className="flex flex-row items-center justify-between px-4 py-3 gap-2"
                >
                    <div className="flex flex-row items-center gap-2">
                        <LemonSkeleton.Circle className="h-3 w-3" />
                        <LemonSkeleton className="h-3 w-24" />
                    </div>
                    <LemonSkeleton className="h-6 w-20" />
                </div>
            )}
            <div
                data-attr="web-analytics-skeleton-chart-bars"
                className="relative flex-1 flex items-end gap-1 px-4 pb-8 pt-2 min-h-56"
            >
                {heights.map((height, i) => (
                    <div
                        key={i}
                        data-attr="web-analytics-skeleton-chart-bar"
                        className="flex-1 flex items-end"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${height}%` }}
                    >
                        <LemonSkeleton className="w-full h-full" />
                    </div>
                ))}
                <div className="absolute bottom-6 left-4 right-4">
                    <LemonSkeleton className="h-px w-full" />
                </div>
            </div>
            <div
                data-attr="web-analytics-skeleton-chart-axis-ticks"
                className="flex flex-row items-center justify-between px-4 pb-3 gap-2"
            >
                {range(AXIS_TICK_COUNT).map((i) => (
                    <LemonSkeleton key={i} className="h-2 w-8" />
                ))}
            </div>
        </div>
    )
}
