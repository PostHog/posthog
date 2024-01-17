import './Elements.scss'

import { useActions, useValues } from 'kea'
import { compactNumber } from 'lib/utils'
import React from 'react'

import { ElementInfoWindow } from '~/toolbar/elements/ElementInfoWindow'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { FocusRect } from '~/toolbar/elements/FocusRect'
import { HeatmapElement } from '~/toolbar/elements/HeatmapElement'
import { HeatmapLabel } from '~/toolbar/elements/HeatmapLabel'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { getBoxColors, getHeatMapHue } from '~/toolbar/utils'

export function Elements(): JSX.Element {
    const {
        heatmapElements,
        elementsToDisplay,
        labelsToDisplay,
        hoverElement,
        selectedElement,
        inspectEnabled,
        highlightElementMeta,
        relativePositionCompensation,
    } = useValues(elementsLogic)
    const { setHoverElement, selectElement } = useActions(elementsLogic)
    const { highestClickCount, shiftPressed } = useValues(heatmapLogic)
    const heatmapPointerEvents = shiftPressed ? 'none' : 'all'

    return (
        <>
            <div
                id="posthog-infowindow-container"
                className="w-full h-full absolute top-0 left-0 pointer-events-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    zIndex: 2147483021,
                }}
            >
                <ElementInfoWindow />
            </div>
            <div
                id="posthog-toolbar-elements"
                className="w-full h-full absolute top-0 pointer-events-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    top: relativePositionCompensation,
                    zIndex: 2147483010,
                }}
            >
                {highlightElementMeta?.rect ? <FocusRect rect={highlightElementMeta.rect} /> : null}

                {elementsToDisplay.map(({ rect, element }, index) => (
                    <HeatmapElement
                        key={`inspect-${index}`}
                        rect={rect}
                        style={{
                            pointerEvents: heatmapPointerEvents,
                            cursor: 'pointer',
                            zIndex: 0,
                            opacity:
                                (!hoverElement && !selectedElement) ||
                                selectedElement === element ||
                                hoverElement === element
                                    ? 1
                                    : 0.4,
                            transition: 'opacity 0.2s, box-shadow 0.2s',
                            ...getBoxColors('blue', hoverElement === element || selectedElement === element),
                        }}
                        onClick={() => selectElement(element)}
                        onMouseOver={() => selectedElement === null && setHoverElement(element)}
                        onMouseOut={() => selectedElement === null && setHoverElement(null)}
                    />
                ))}

                {heatmapElements.map(({ rect, count, clickCount, rageclickCount, element }, index) => {
                    return (
                        <React.Fragment key={`heatmap-${index}`}>
                            <HeatmapElement
                                rect={rect}
                                style={{
                                    pointerEvents: inspectEnabled ? 'none' : heatmapPointerEvents,
                                    zIndex: 1,
                                    opacity: !hoverElement || hoverElement === element ? 1 : 0.4,
                                    transition: 'opacity 0.2s, box-shadow 0.2s',
                                    cursor: 'pointer',
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
                                <HeatmapLabel
                                    rect={rect}
                                    style={{
                                        pointerEvents: heatmapPointerEvents,
                                        zIndex: 5,
                                        opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                                        transition: 'opacity 0.2s, transform 0.2s linear',
                                        transform: hoverElement === element ? 'scale(1.3)' : 'none',
                                        cursor: 'pointer',
                                        color: `hsla(${getHeatMapHue(
                                            clickCount || 0,
                                            highestClickCount
                                        )}, 20%, 12%, 1)`,
                                        background: `hsla(${getHeatMapHue(
                                            clickCount || 0,
                                            highestClickCount
                                        )}, 100%, 62%, 1)`,
                                        boxShadow: `hsla(${getHeatMapHue(
                                            clickCount || 0,
                                            highestClickCount
                                        )}, 100%, 32%, 1) 0px 1px 5px 1px`,
                                    }}
                                    onClick={() => selectElement(element)}
                                    onMouseOver={() => selectedElement === null && setHoverElement(element)}
                                    onMouseOut={() => selectedElement === null && setHoverElement(null)}
                                >
                                    {compactNumber(clickCount || 0)}
                                </HeatmapLabel>
                            )}
                            {!!rageclickCount && (
                                <HeatmapLabel
                                    rect={rect}
                                    style={{
                                        pointerEvents: heatmapPointerEvents,
                                        zIndex: 5,
                                        opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                                        transition: 'opacity 0.2s, transform 0.2s linear',
                                        transform: hoverElement === element ? 'scale(1.3)' : 'none',
                                        cursor: 'pointer',
                                        color: `hsla(${getHeatMapHue(
                                            rageclickCount || 0,
                                            highestClickCount
                                        )}, 20%, 12%, 1)`,
                                        background: `hsla(${getHeatMapHue(
                                            rageclickCount || 0,
                                            highestClickCount
                                        )}, 100%, 62%, 1)`,
                                        boxShadow: `hsla(${getHeatMapHue(
                                            rageclickCount || 0,
                                            highestClickCount
                                        )}, 100%, 32%, 1) 0px 1px 5px 1px`,
                                    }}
                                    align="left"
                                    onClick={() => selectElement(element)}
                                    onMouseOver={() => selectedElement === null && setHoverElement(element)}
                                    onMouseOut={() => selectedElement === null && setHoverElement(null)}
                                >
                                    {compactNumber(rageclickCount)}&#128545;
                                </HeatmapLabel>
                            )}
                        </React.Fragment>
                    )
                })}

                {labelsToDisplay.map(({ element, rect, index }, loopIndex) => {
                    if (rect) {
                        return (
                            <HeatmapLabel
                                key={`label-${loopIndex}`}
                                rect={rect}
                                align="left"
                                style={{
                                    zIndex: 5,
                                    opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                                    transition: 'opacity 0.2s, transform 0.2s linear',
                                    transform: hoverElement === element ? 'scale(1.3)' : 'none',
                                    pointerEvents: heatmapPointerEvents,
                                    cursor: 'pointer',
                                    color: 'hsla(141, 21%, 12%, 1)',
                                    background: 'hsl(147, 100%, 62%)',
                                    boxShadow: 'hsla(141, 100%, 32%, 1) 0px 1px 5px 1px',
                                }}
                                onClick={() => selectElement(element)}
                                onMouseOver={() => selectedElement === null && setHoverElement(element)}
                                onMouseOut={() => selectedElement === null && setHoverElement(null)}
                            >
                                {(index || loopIndex) + 1}
                            </HeatmapLabel>
                        )
                    }
                })}
            </div>
        </>
    )
}
