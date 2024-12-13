import clsx from 'clsx'
import { useValues } from 'kea'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { toolbarConfigLogic } from '../toolbarConfigLogic'
import { useMousePosition } from './useMousePosition'

function ScrollDepthMouseInfo(): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)
    const { heatmapElements, rawHeatmapLoading, shiftPressed } = useValues(heatmapLogic)

    const { y: mouseY } = useMousePosition()

    if (!mouseY) {
        return null
    }

    const scrollOffset = (posthog as any).scrollManager.scrollY()
    const scrolledMouseY = mouseY + scrollOffset

    const elementInMouseY = heatmapElements.find((x, i) => {
        const lastY = heatmapElements[i - 1]?.y ?? 0
        return scrolledMouseY >= lastY && scrolledMouseY < x.y
    })

    const maxCount = heatmapElements[0]?.count ?? 0
    const percentage = ((elementInMouseY?.count ?? 0) / maxCount) * 100

    return (
        <div
            className="absolute left-0 right-0 flex items-center z-10 -translate-y-1/2"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                top: mouseY,
            }}
        >
            <div className="border-b border-default w-full opacity-75" />
            <div
                className={clsx(
                    'bg-default whitespace-nowrap text-white rounded p-2 font-semibold opacity-75 hover:opacity-100 transition-all',
                    !shiftPressed ? 'pointer-events-auto' : 'pointer-events-none'
                )}
            >
                {rawHeatmapLoading ? (
                    <>Loading...</>
                ) : heatmapElements.length ? (
                    <>{percentage.toPrecision(4)}% scrolled this far</>
                ) : (
                    <>No scroll data for the current dimension range</>
                )}
            </div>

            <div className="border-b border-default w-10 opacity-75" />
        </div>
    )
}

export function ScrollDepth(): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)

    const { heatmapEnabled, heatmapFilters, heatmapElements, scrollDepthPosthogJsError, heatmapColorPalette } =
        useValues(heatmapLogic)

    if (!heatmapEnabled || !heatmapFilters.enabled || heatmapFilters.type !== 'scrolldepth') {
        return null
    }

    if (scrollDepthPosthogJsError) {
        return null
    }

    const scrollOffset = (posthog as any).scrollManager.scrollY()

    // We want to have a fading color from red to orange to green to blue to grey, fading from the highest count to the lowest
    const maxCount = heatmapElements[0]?.count ?? 0

    function color(count: number): string {
        const value = 1 - count / maxCount

        if (heatmapColorPalette === 'default') {
            const safeValue = Math.max(0, Math.min(1, value))
            const hue = Math.round(260 * safeValue)

            // Return hsl color. You can adjust saturation and lightness to your liking
            return `hsl(${hue}, 100%, 50%)`
        }

        const rgba = [0, 0, 0, count / maxCount]

        switch (heatmapColorPalette) {
            case 'red':
                rgba[0] = 255
                break
            case 'green':
                rgba[1] = 255
                break
            case 'blue':
                rgba[2] = 255
                break
            default:
                break
        }

        return `rgba(${rgba.join(', ')})`
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
                {heatmapElements.map(({ y, count }, i) => (
                    <div
                        key={y}
                        className="absolute left-0 w-full opacity-50"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            top: heatmapElements[i - 1]?.y ?? 0,
                            height: y - (heatmapElements[i - 1]?.y ?? 0),
                            backgroundColor: color(count),
                        }}
                    />
                ))}
            </div>
            <ScrollDepthMouseInfo />
        </div>
    )
}
