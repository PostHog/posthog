import { useValues } from 'kea'
import { useMemo } from 'react'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { useMousePosition } from 'lib/components/heatmaps/useMousePosition'
import { cn } from 'lib/utils/css-classes'

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
        <div
            className="absolute left-0 right-0 flex items-center z-10 -translate-y-1/2"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                top: adjustedMouseY,
            }}
        >
            <div className="border-b border-default w-full opacity-75" />
            <div className="bg-default whitespace-nowrap text-white rounded p-2 font-semibold opacity-75 hover:opacity-100 transition-all pointer-events-auto">
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

    const colorFunction = useMemo(() => {
        const maxCount = heatmapElements[0]?.count ?? 0

        return (count: number): string => {
            const value = 1 - count / maxCount

            if (heatmapColorPalette === 'default') {
                const safeValue = Math.max(0, Math.min(1, value))
                const hue = Math.round(260 * safeValue)
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
    }, [heatmapElements, heatmapColorPalette])

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
                            backgroundColor: colorFunction(count),
                        }}
                    />
                ))}
            </div>
            <ScrollDepthMouseInfo context={context} exportToken={exportToken} />
        </div>
    )
}
