import { useValues } from 'kea'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { toolbarConfigLogic } from '../toolbarConfigLogic'
import { HeatmapType } from '../types'
import { elementsLogic } from './elementsLogic'

export function HeatmapElement({ element }: { element: HeatmapType }): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)
    const { inspectEnabled } = useValues(elementsLogic)
    const { shiftPressed } = useValues(heatmapLogic)
    const heatmapPointerEvents = shiftPressed ? 'none' : 'all'
    const size = 36 // TODO: How to decide on radius
    const opacity = Math.max(0.2, Math.min(0.7, element.count / 1000)) // TODO: How to decide on opacity

    // Remove as any once we have the scrollmanager stuff merged
    const ph = posthog as any

    const scrollYOffset = element.target_fixed ? 0 : ph.scrollManager.scrollY()
    const scrollXOffset = element.target_fixed ? 0 : ph.scrollManager.scrollX()

    const color = element.type === 'click' ? 'red' : 'blue'

    // TODO: We need to move all this into the logic and let it take care of reducing everything down
    const mode = 'percentage'

    // Default mode - place it exactly where it should be
    const top = `${element.y - size * 0.5 - scrollYOffset}px`
    let left = `${element.x - size * 0.5 - scrollXOffset}px`

    if (mode === 'percentage') {
        // Scale the x axis to account for different browser widths
        left = `calc(${(element.x / element.viewport_width) * 100}% - ${size * 0.5}px)`
    }

    return (
        <div
            className="absolute rounded-full hover:scale-110 transition-transform duration-75 ease-in-out"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                pointerEvents: inspectEnabled ? 'none' : heatmapPointerEvents,
                zIndex: 1,
                top,
                left,
                width: size,
                height: size,
                opacity,
                backgroundColor: color,
                boxShadow: `0px 0px 10px 10px ${color}`,
            }}
        />
    )
}

export function Heatmap(): JSX.Element | null {
    const { heatmap, heatmapEnabled, heatmapFilter } = useValues(heatmapLogic)

    if (!heatmapEnabled) {
        return null
    }

    const squareSize = 16

    const xNum = window.innerWidth / squareSize
    const yNum = window.innerHeight / squareSize

    return (
        <div className="fixed inset-0 overflow-hidden">
            {/* {Array.from({ length: xNum }, (_, x) =>
                Array.from({ length: yNum }, (_, y) => (
                    <div
                        key={`${x}-${y}`}
                        className="absolute"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            top: `${y * squareSize}px`,
                            left: `${x * squareSize}px`,
                            width: squareSize,
                            height: squareSize,
                            backgroundColor: 'rgba(255, 0, 0, 0.1)',
                            border: '1px solid rgba(255, 0, 0, 0.3)',
                            boxSizing: 'border-box',
                        }}
                    />
                ))
            )} */}

            {heatmap?.results.map((x, i) => (
                <HeatmapElement key={i} element={x} />
            ))}
        </div>
    )
}
