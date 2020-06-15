import React from 'react'
import { useActions, useValues } from 'kea'
import { heatmapLogic } from '~/toolbar/shared/heatmapLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { FocusRect } from '~/toolbar/shared/FocusRect'
import { inspectElementLogic } from '~/toolbar/shared/inspectElementLogic'
import { ElementMetadata } from '~/toolbar/shared/ElementMetadata'
import { InspectElementRect } from '~/toolbar/shared/InspectElementRect'
import { HeatmapElement } from '~/toolbar/shared/HeatmapElement'
import { HeatmapLabel } from '~/toolbar/shared/HeatmapLabel'

export function Heatmap() {
    const {
        countedElementsWithRects,
        showElementFinder,
        highestEventCount,
        selectedElement,
        selectedElementMeta,
        highlightedElement,
        highlightedElementMeta,
    } = useValues(heatmapLogic)
    const { highlightElement, selectElement } = useActions(heatmapLogic)
    const { domZoom, domPadding } = useValues(dockLogic)
    const {
        selecting: inspectElementActive,
        element: inspectSelectedElement,
        actionStep: inspectActionStep,
        selectableElementsWithRects: inspectSelectableElements,
    } = useValues(inspectElementLogic)
    const { start: startInspect, selectElement: selectInspectElement } = useActions(inspectElementLogic)

    let highlightedRect
    let highlightedMeta
    let highlightPointerEvents = false
    let highlightOnClose

    if (highlightedElement && (selectedElement !== highlightedElement || inspectSelectedElement)) {
        highlightedRect = highlightedElement.getBoundingClientRect()
        highlightedMeta = highlightedElementMeta
        if (highlightedElement === inspectSelectedElement) {
            highlightPointerEvents = true
            highlightOnClose = inspectElementActive ? null : () => startInspect(true)
        }
    } else if (inspectSelectedElement) {
        highlightedRect = inspectSelectedElement.getBoundingClientRect()
        highlightedMeta = { element: inspectSelectedElement, actionStep: inspectActionStep }
        highlightPointerEvents = !inspectElementActive
        highlightOnClose = inspectElementActive ? null : () => startInspect(true)
    } else if (selectedElement) {
        highlightedRect = selectedElement.getBoundingClientRect()
        highlightedMeta = selectedElementMeta
        highlightPointerEvents = true
        highlightOnClose = () => selectElement(null)
    }

    return (
        <div
            id="posthog-heatmap"
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
            {highlightedRect && showElementFinder ? <FocusRect rect={highlightedRect} /> : null}
            {inspectSelectedElement ? <InspectElementRect /> : null}
            {highlightedRect && !showElementFinder && highlightedMeta ? (
                <ElementMetadata
                    rect={highlightedRect}
                    meta={highlightedMeta}
                    pointerEvents={highlightPointerEvents}
                    onClose={highlightOnClose}
                />
            ) : null}
            {inspectSelectableElements.map(({ rect }, index) => (
                <HeatmapElement
                    key={`inspect-${index}`}
                    rect={rect}
                    domPadding={domPadding}
                    domZoom={domZoom}
                    style={{
                        pointerEvents: 'none',
                        zIndex: 0,
                        opacity: 1,
                        backgroundBlendMode: 'multiply',
                        background: 'hsla(240, 90%, 58%, 0.2)',
                        boxShadow: `hsla(240, 90%, 27%, 0.5) 0px 3px 10px 2px`,
                    }}
                />
            ))}
            {countedElementsWithRects.map(({ rect, count, element }, index) => {
                return (
                    <React.Fragment key={index}>
                        <HeatmapElement
                            rect={rect}
                            domPadding={domPadding}
                            domZoom={domZoom}
                            style={{
                                pointerEvents: inspectElementActive ? 'none' : 'all',
                                zIndex: 1,
                                opacity: highlightedElement && highlightedElement !== element ? 0.4 : 1,
                                transition: 'opacity 0.2s, box-shadow 0.2s',
                                cursor: 'pointer',
                                backgroundBlendMode: 'multiply',
                                background: `hsla(4, 90%, 58%, ${(count / highestEventCount) * 0.4})`,
                                boxShadow: `hsla(4, 90%, 27%, 0.8) 0px 3px 10px ${
                                    highlightedElement === element ? 4 : 2
                                }px`,
                            }}
                            onClick={() => {
                                if (inspectSelectedElement && !inspectElementActive) {
                                    selectInspectElement(element)
                                } else {
                                    selectElement(element)
                                }
                            }}
                            onMouseOver={() => highlightElement(element)}
                            onMouseOut={() => highlightElement(null)}
                        />
                        <HeatmapLabel
                            rect={rect}
                            domPadding={domPadding}
                            domZoom={domZoom}
                            label={<>{index + 1}</>}
                            style={{
                                zIndex: 5,
                                opacity: highlightedElement && highlightedElement !== element ? 0.4 : 1,
                                transition: 'opacity 0.2s, transform 0.2s linear',
                                transform: highlightedElement === element ? 'scale(1.3)' : 'none',
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
