import { useValues } from 'kea'

import { ScrollDepthMouseCanvas, scrollDepthColor } from 'lib/components/heatmaps/ScrollDepthCanvas'
import { useMousePosition } from 'lib/components/heatmaps/useMousePosition'
import { useShiftKeyPressed } from 'lib/components/heatmaps/useShiftKeyPressed'

import { heatmapToolbarMenuLogic } from '~/toolbar/elements/heatmapToolbarMenuLogic'

import { toolbarConfigLogic } from '../toolbarConfigLogic'

function ScrollDepthMouseInfo(): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)
    const { heatmapElements, rawHeatmapLoading } = useValues(heatmapToolbarMenuLogic)

    const shiftPressed = useShiftKeyPressed()
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
        <ScrollDepthMouseCanvas
            mouseY={mouseY}
            shiftPressed={shiftPressed}
            rawHeatmapLoading={rawHeatmapLoading}
            heatmapElements={heatmapElements}
            percentage={percentage}
        />
    )
}

export function ScrollDepth(): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)

    const { heatmapEnabled, heatmapFilters, heatmapElements, scrollDepthPosthogJsError, heatmapColorPalette } =
        useValues(heatmapToolbarMenuLogic)

    if (!heatmapEnabled || !heatmapFilters.enabled || heatmapFilters.type !== 'scrolldepth') {
        return null
    }

    if (scrollDepthPosthogJsError) {
        return null
    }

    const scrollOffset = (posthog as any).scrollManager.scrollY()

    // We want to have a fading color from red to orange to green to blue to grey, fading from the highest count to the lowest
    const maxCount = heatmapElements[0]?.count ?? 0

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
                            backgroundColor: scrollDepthColor(count, maxCount, heatmapColorPalette),
                        }}
                    />
                ))}
            </div>
            <ScrollDepthMouseInfo />
        </div>
    )
}
