import { useValues } from 'kea'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { useMousePosition } from 'lib/components/heatmaps/useMousePosition'
import { cn } from 'lib/utils/css-classes'

import { ScrollDepthMouseCanvas, scrollDepthColor } from '~/toolbar/elements/ScrollDepth'

function ScrollDepthMouseInfo({
    context,
    exportToken,
}: {
    context: 'in-app' | 'toolbar'
    exportToken?: string
}): JSX.Element | null {
    const { heatmapElements, rawHeatmapLoading, heatmapScrollY } = useValues(heatmapDataLogic({ context, exportToken }))

    const { y: mouseY } = useMousePosition()

    if (!mouseY) {
        return null
    }

    // Get the iframe's offset from the top of the viewport
    const iframe = document.getElementById('heatmap-iframe')
    if (!iframe) {
        return null
    }
    const iframeTop = iframe.getBoundingClientRect().top
    const relativeMouseY = mouseY - iframeTop
    const adjustedMouseY = relativeMouseY < 0 ? 0 : relativeMouseY

    const scrolledMouseY = adjustedMouseY + heatmapScrollY

    const elementInMouseY = heatmapElements.find((x, i) => {
        const lastY = heatmapElements[i - 1]?.y ?? 0
        return scrolledMouseY >= lastY && scrolledMouseY < x.y
    })

    const maxCount = heatmapElements[0]?.count ?? 0
    const percentage = ((elementInMouseY?.count ?? 0) / maxCount) * 100

    return (
        <ScrollDepthMouseCanvas
            mouseY={adjustedMouseY}
            shiftPressed={false}
            rawHeatmapLoading={rawHeatmapLoading}
            heatmapElements={heatmapElements}
            percentage={percentage}
        />
    )
}

export function ScrollDepthCanvas({
    positioning = 'fixed',
    context = 'in-app',
    exportToken,
}: {
    positioning?: 'absolute' | 'fixed'
    context?: 'in-app' | 'toolbar'
    exportToken?: string
}): JSX.Element | null {
    const { heatmapElements, heatmapColorPalette, heatmapScrollY, isReady } = useValues(
        heatmapDataLogic({ context, exportToken })
    )
    const maxCount = heatmapElements[0]?.count ?? 0

    if (!heatmapElements.length) {
        return null
    }

    return (
        <div
            className={cn(
                'inset-0 overflow-hidden w-full h-full',
                positioning,
                isReady ? 'heatmaps-ready' : 'heatmaps-loading'
            )}
            data-attr="scroll-depth-canvas"
        >
            <div
                className="absolute top-0 left-0 right-0"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    transform: `translateY(${-heatmapScrollY}px)`,
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
            <ScrollDepthMouseInfo context={context} exportToken={exportToken} />
        </div>
    )
}
