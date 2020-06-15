import './Elements.scss'

import React from 'react'
import { useActions, useValues } from 'kea'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { FocusRect } from '~/toolbar/elements/FocusRect'
import { ElementMetadata } from '~/toolbar/elements/ElementMetadata'
import { HeatmapElement } from '~/toolbar/elements/HeatmapElement'
import { HeatmapLabel } from '~/toolbar/elements/HeatmapLabel'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'

export function Elements() {
    const { domZoom, domPadding } = useValues(dockLogic)
    const {
        heatmapElements,
        inspectElements,
        hoverElement,
        inspectEnabled,
        hoverElementMeta,
        hoverElementHighlight,
    } = useValues(elementsLogic)
    const { setHoverElement, setSelectedElement } = useActions(elementsLogic)
    const { highestEventCount } = useValues(heatmapLogic)

    return (
        <div
            id="posthog-toolbar-elements"
            style={{
                width: '100%',
                height: '100%',
                position: 'absolute',
                top: 0,
                left: 0,
                zIndex: '2147483010',
                pointerEvents: 'none',
            }}
        >
            {hoverElementMeta && hoverElementHighlight ? <FocusRect rect={hoverElementMeta.rect} /> : null}
            <ElementMetadata />

            {inspectElements.map(({ rect, element }, index) => (
                <HeatmapElement
                    key={`inspect-${index}`}
                    rect={rect}
                    domPadding={domPadding}
                    domZoom={domZoom}
                    style={{
                        pointerEvents: 'all',
                        cursor: 'pointer',
                        zIndex: 0,
                        opacity: !hoverElement || hoverElement === element ? 1 : 0.4,
                        transition: 'opacity 0.2s, box-shadow 0.2s',
                        backgroundBlendMode: 'multiply',
                        background: 'hsla(240, 90%, 58%, 0.2)',
                        boxShadow: `hsla(240, 90%, 27%, 0.5) 0px 3px 10px ${hoverElement === element ? 4 : 2}px`,
                    }}
                    onClick={() => setSelectedElement(element)}
                    onMouseOver={() => setHoverElement(element)}
                    onMouseOut={() => setHoverElement(null)}
                />
            ))}

            {heatmapElements.map(({ rect, count, element }, index) => {
                return (
                    <React.Fragment key={index}>
                        <HeatmapElement
                            rect={rect}
                            domPadding={domPadding}
                            domZoom={domZoom}
                            style={{
                                pointerEvents: inspectEnabled ? 'none' : 'all',
                                zIndex: 1,
                                opacity: !hoverElement || hoverElement === element ? 1 : 0.4,
                                transition: 'opacity 0.2s, box-shadow 0.2s',
                                cursor: 'pointer',
                                backgroundBlendMode: 'multiply',
                                background: `hsla(4, 90%, 58%, ${(count / highestEventCount) * 0.4})`,
                                boxShadow: `hsla(4, 90%, 27%, 0.8) 0px 3px 10px ${hoverElement === element ? 4 : 2}px`,
                            }}
                            onClick={() => setSelectedElement(element)}
                            onMouseOver={() => setHoverElement(element)}
                            onMouseOut={() => setHoverElement(null)}
                        />
                        <HeatmapLabel
                            rect={rect}
                            domPadding={domPadding}
                            domZoom={domZoom}
                            label={<>{index + 1}</>}
                            style={{
                                zIndex: 5,
                                opacity: hoverElement && hoverElement !== element ? 0.4 : 1,
                                transition: 'opacity 0.2s, transform 0.2s linear',
                                transform: hoverElement === element ? 'scale(1.3)' : 'none',
                                pointerEvents: 'none',
                            }}
                        >
                            {index + 1}
                        </HeatmapLabel>
                    </React.Fragment>
                )
            })}
        </div>
    )
}
