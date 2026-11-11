import { Fragment, memo } from 'react'

import { compactNumber } from 'lib/utils/numbers'

import { AutocaptureElement } from '~/toolbar/shared/elements/AutocaptureElement'
import { AutocaptureElementLabel } from '~/toolbar/shared/elements/AutocaptureElementLabel'
import { ElementWithMetadata } from '~/toolbar/shared/types'
import { getBoxColors, getHeatMapHue } from '~/toolbar/shared/utils'

let nextElementId = 0
const elementIdMap = new WeakMap<HTMLElement, number>()

export function getStableElementId(element: HTMLElement): number {
    let id = elementIdMap.get(element)
    if (id === undefined) {
        id = nextElementId++
        elementIdMap.set(element, id)
    }
    return id
}

interface HeatmapOverlayElementsProps {
    heatmapElements: ElementWithMetadata[]
    hoverElement: HTMLElement | null
    selectedElement: HTMLElement | null
    inspectEnabled: boolean
    heatmapPointerEvents: 'none' | 'all'
    highestClickCount: number
    selectElement: (element: HTMLElement) => void
    setHoverElement: (element: HTMLElement | null) => void
}

export const HeatmapOverlayElements = memo(function HeatmapOverlayElements({
    heatmapElements,
    hoverElement,
    selectedElement,
    inspectEnabled,
    heatmapPointerEvents,
    highestClickCount,
    selectElement,
    setHoverElement,
}: HeatmapOverlayElementsProps): JSX.Element {
    return (
        <>
            {heatmapElements.map(({ rect, count, clickCount, rageclickCount, deadclickCount, element, visible }) => {
                if (!visible) {
                    return null
                }
                const elementId = getStableElementId(element)
                return (
                    <Fragment key={`heatmap-${elementId}`}>
                        <AutocaptureElement
                            rect={rect}
                            style={{
                                pointerEvents: inspectEnabled ? 'none' : heatmapPointerEvents,
                                zIndex: hoverElement === element ? 4 : 3,
                                opacity: !hoverElement || hoverElement === element ? 1 : 0.4,
                                transition: 'opacity 0.2s, box-shadow 0.2s',
                                cursor: 'pointer',
                                borderRadius: 5,
                                ...getBoxColors(
                                    'red',
                                    hoverElement === element,
                                    ((count || 0) / highestClickCount) * 0.4
                                ),
                            }}
                            onClick={() => selectElement(element)}
                            onMouseOver={() => selectedElement === null && setHoverElement(element)}
                            onMouseOut={() => selectedElement === null && setHoverElement(null)}
                        />
                        {!!clickCount && (
                            <AutocaptureElementLabel
                                rect={rect}
                                style={{
                                    pointerEvents: heatmapPointerEvents,
                                    zIndex: 5,
                                    opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                                    transition: 'opacity 0.2s, transform 0.2s linear',
                                    transform: hoverElement === element ? 'scale(1.3)' : 'none',
                                    cursor: 'pointer',
                                    color: `hsla(${getHeatMapHue(clickCount || 0, highestClickCount)}, 20%, 12%, 1)`,
                                    background: `hsla(${getHeatMapHue(clickCount || 0, highestClickCount)}, 100%, 62%, 1)`,
                                    boxShadow: `hsla(${getHeatMapHue(clickCount || 0, highestClickCount)}, 100%, 32%, 1) 0px 1px 5px 1px`,
                                }}
                                onClick={() => selectElement(element)}
                                onMouseOver={() => selectedElement === null && setHoverElement(element)}
                                onMouseOut={() => selectedElement === null && setHoverElement(null)}
                            >
                                {compactNumber(clickCount || 0)}
                            </AutocaptureElementLabel>
                        )}
                        {!!rageclickCount && (
                            <AutocaptureElementLabel
                                rect={rect}
                                style={{
                                    pointerEvents: heatmapPointerEvents,
                                    zIndex: 5,
                                    opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                                    transition: 'opacity 0.2s, transform 0.2s linear',
                                    transform: hoverElement === element ? 'scale(1.3)' : 'none',
                                    cursor: 'pointer',
                                    color: `hsla(${getHeatMapHue(rageclickCount || 0, highestClickCount)}, 20%, 12%, 1)`,
                                    background: `hsla(${getHeatMapHue(rageclickCount || 0, highestClickCount)}, 100%, 62%, 1)`,
                                    boxShadow: `hsla(${getHeatMapHue(rageclickCount || 0, highestClickCount)}, 100%, 32%, 1) 0px 1px 5px 1px`,
                                }}
                                align="left"
                                onClick={() => selectElement(element)}
                                onMouseOver={() => selectedElement === null && setHoverElement(element)}
                                onMouseOut={() => selectedElement === null && setHoverElement(null)}
                            >
                                {compactNumber(rageclickCount)}&#128545;
                            </AutocaptureElementLabel>
                        )}
                        {!!deadclickCount && (
                            <AutocaptureElementLabel
                                rect={rect}
                                style={{
                                    pointerEvents: heatmapPointerEvents,
                                    zIndex: 5,
                                    opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                                    transition: 'opacity 0.2s, transform 0.2s linear',
                                    transform: hoverElement === element ? 'scale(1.3)' : 'none',
                                    cursor: 'pointer',
                                    color: `hsla(${getHeatMapHue(deadclickCount || 0, highestClickCount)}, 20%, 12%, 1)`,
                                    background: `hsla(${getHeatMapHue(deadclickCount || 0, highestClickCount)}, 100%, 62%, 1)`,
                                    boxShadow: `hsla(${getHeatMapHue(deadclickCount || 0, highestClickCount)}, 100%, 32%, 1) 0px 1px 5px 1px`,
                                }}
                                align="left"
                                onClick={() => selectElement(element)}
                                onMouseOver={() => selectedElement === null && setHoverElement(element)}
                                onMouseOut={() => selectedElement === null && setHoverElement(null)}
                            >
                                {compactNumber(deadclickCount)}&#128565;
                            </AutocaptureElementLabel>
                        )}
                    </Fragment>
                )
            })}
        </>
    )
})
