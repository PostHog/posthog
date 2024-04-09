import { useValues } from 'kea'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { HeatmapType } from '../types'
import { elementsLogic } from './elementsLogic'

export function HeatmapElement({ element }: { element: HeatmapType }): JSX.Element | null {
    const { inspectEnabled } = useValues(elementsLogic)
    const { shiftPressed } = useValues(heatmapLogic)
    const heatmapPointerEvents = shiftPressed ? 'none' : 'all'
    const size = 36 // TODO: How to decide on radius
    const opacity = Math.max(0.2, Math.min(0.7, element.count / 1000)) // TODO: How to decide on opacity

    return (
        <div
            className="absolute rounded-full"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                pointerEvents: inspectEnabled ? 'none' : heatmapPointerEvents,
                zIndex: 1,
                top: `${element.y - size * 0.5 + window.pageYOffset}px`,
                left: `${element.x - size * 0.5 + window.pageXOffset}px`,
                width: size,
                height: size,
                opacity,
                backgroundColor: 'red',
                boxShadow: '0px 0px 10px 10px red',
            }}
        />
    )
}

export function Heatmap(): JSX.Element | null {
    const { heatmap, heatmapEnabled } = useValues(heatmapLogic)

    const items = heatmap?.results

    if (!items?.length || !heatmapEnabled) {
        return null
    }

    return (
        <>
            {items.map((x, i) => (
                <HeatmapElement key={i} element={x} />
            ))}
        </>
    )
}
