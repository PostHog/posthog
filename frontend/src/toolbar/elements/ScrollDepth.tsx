import { useValues } from 'kea'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { toolbarConfigLogic } from '../toolbarConfigLogic'

export function ScrollDepth(): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)

    const { heatmap, heatmapEnabled, heatmapFilter } = useValues(heatmapLogic)

    if (!heatmapEnabled || !heatmapFilter.scrolldepth) {
        return null
    }

    const scrollDepths = [
        { depth: 0, count: 10000 },
        { depth: 100, count: 10000 },
        { depth: 200, count: 9880 },
        { depth: 300, count: 9000 },
        { depth: 400, count: 8000 },
        { depth: 500, count: 8000 },
        { depth: 600, count: 8000 },
        { depth: 700, count: 8000 },
        { depth: 800, count: 6000 },
        { depth: 900, count: 3000 },
        { depth: 1000, count: 2000 },
        { depth: 1100, count: 1000 },
        { depth: 1300, count: 0 },
    ]

    // Remove as any once we have the scrollmanager stuff merged
    const ph = posthog as any

    const scrollOffset = ph.scrollManager.scrollY()

    // We want to have a fading color from red to orange to green to blue to grey, fading from the highest coun to the lowest

    const maxCount = scrollDepths[0].count

    function color(count: number): string {
        const value = 1 - count / maxCount

        const safeValue = Math.max(0, Math.min(1, value))

        // Calculate hue

        const hue = Math.round(260 * safeValue)

        // Return hsl color. You can adjust saturation and lightness to your liking
        return `hsl(${hue}, 100%, 50%)`
    }

    return (
        <div className="fixed inset-0 overflow-hidden">
            <div
                className="absolute top-0 left-0 right-0"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    transform: `translateY(${-scrollOffset}px)`,
                }}
            >
                {scrollDepths.map(({ depth, count }) => (
                    <div
                        key={depth}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            position: 'absolute',
                            top: depth,
                            left: 0,
                            width: '100%',
                            height: 100,
                            backgroundColor: color(count),
                            opacity: 0.5,
                        }}
                    />
                ))}
            </div>
        </div>
    )
}
