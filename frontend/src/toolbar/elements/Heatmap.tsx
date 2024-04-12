import { useValues } from 'kea'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { toolbarConfigLogic } from '../toolbarConfigLogic'
import { HeatmapElement } from '../types'
import { elementsLogic } from './elementsLogic'

function HeatmapElementView({ element }: { element: HeatmapElement }): JSX.Element | null {
    const { posthog } = useValues(toolbarConfigLogic)
    const { inspectEnabled } = useValues(elementsLogic)
    const { shiftPressed } = useValues(heatmapLogic)
    const heatmapPointerEvents = shiftPressed ? 'none' : 'all'
    const size = 36 // TODO: How to decide on radius
    const opacity = Math.max(0.2, Math.min(0.7, element.count / 1000)) // TODO: How to decide on opacity

    // Remove as any once we have the scrollmanager stuff merged
    const ph = posthog as any

    const { xPercentage, y, targetFixed } = element

    const scrollYOffset = targetFixed ? 0 : ph.scrollManager.scrollY()

    // Default mode - place it exactly where it should be
    const top = `${y - size * 0.5 - scrollYOffset}px`
    const left = `calc(${xPercentage * 100}% - ${size * 0.5}px)`

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
                backgroundColor: 'red',
                boxShadow: `0px 0px 10px 10px red`,
            }}
        />
    )
}

export function Heatmap(): JSX.Element | null {
    const { heatmapElements, heatmapEnabled, heatmapFilters } = useValues(heatmapLogic)

    if (!heatmapEnabled || !heatmapFilters.enabled || heatmapFilters.type === 'scrolldepth') {
        return null
    }

    return (
        <div className="fixed inset-0 overflow-hidden">
            {heatmapElements?.map((x, i) => (
                <HeatmapElementView key={i} element={x} />
            ))}
        </div>
    )
}
