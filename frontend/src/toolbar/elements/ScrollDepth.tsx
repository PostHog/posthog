import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { toolbarConfigLogic } from '../toolbarConfigLogic'

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

const reversedScrollDepths = [...scrollDepths].reverse()

function ScrollDepthMouseInfo(): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)

    // Track the mouse position and render an indicator about how many people have scrolled to this point

    const [mouseY, setMouseY] = useState<null | number>(0)

    // Remove as any once we have the scrollmanager stuff merged
    const ph = posthog as any
    const scrollOffset = ph.scrollManager.scrollY()
    const countAtThisDepth = reversedScrollDepths.find((x) => x.depth < scrollOffset + mouseY)
    const percentage = ((countAtThisDepth?.count ?? 0) / scrollDepths[0].count) * 100

    useEffect(() => {
        const onMove = (e: MouseEvent): void => {
            setMouseY(e.clientY)
        }

        window.addEventListener('mousemove', onMove)
        return () => {
            window.removeEventListener('mousemove', onMove)
        }
    }, [])

    if (!mouseY) {
        return null
    }

    return (
        <div
            className="absolute left-0 right-0 flex items-center"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                top: mouseY,
                transform: 'translateY(-50%)',
            }}
        >
            <div className="border-b w-full" />
            <div className="bg-border whitespace-nowrap text-default rounded p-2 font-semibold">
                {percentage.toPrecision(4)}% scrolled this far
            </div>

            <div className="border-b w-10" />
        </div>
    )
}

export function ScrollDepth(): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)

    const { heatmapEnabled, heatmapFilter } = useValues(heatmapLogic)

    if (!heatmapEnabled || !heatmapFilter.scrolldepth) {
        return null
    }

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
            <ScrollDepthMouseInfo />
        </div>
    )
}
