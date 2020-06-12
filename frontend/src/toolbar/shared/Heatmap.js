import React from 'react'
import { useActions, useValues } from 'kea'
import { heatmapLogic } from '~/toolbar/shared/heatmapLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { FocusRect } from '~/toolbar/shared/FocusRect'
import { inspectElementLogic } from '~/toolbar/shared/inspectElementLogic'
import { ElementMetadata } from '~/toolbar/shared/ElementMetadata'
import { InspectElementRect } from '~/toolbar/shared/InspectElementRect'

export function Heatmap({ apiURL, temporaryToken }) {
    const logic = heatmapLogic({ apiURL, temporaryToken })
    const {
        countedElementsWithRects,
        showElementFinder,
        highestEventCount,
        selectedElement,
        selectedElementMeta,
        highlightedElement,
        highlightedElementMeta,
    } = useValues(logic)
    const { highlightElement, selectElement } = useActions(logic)
    const { domZoom, domPadding } = useValues(dockLogic)
    const {
        selecting: inspectElementActive,
        element: inspectSelectedElement,
        actionStep: inspectActionStep,
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
            {countedElementsWithRects.map(({ rect, count, element }, index) => {
                return (
                    <React.Fragment key={index}>
                        <div
                            style={{
                                pointerEvents: inspectElementActive ? 'none' : 'all',
                                position: 'absolute',
                                top: `${(rect.top - domPadding + window.pageYOffset) / domZoom}px`,
                                left: `${(rect.left - domPadding + window.pageXOffset) / domZoom}px`,
                                width: `${(rect.right - rect.left) / domZoom}px`,
                                height: `${(rect.bottom - rect.top) / domZoom}px`,
                                zIndex: 1,
                                opacity: highlightedElement && highlightedElement !== element ? 0.4 : 1,
                                transition: 'opacity 0.2s, box-shadow 0.2s',
                                cursor: 'pointer',
                                backgroundBlendMode: 'multiply',
                                // green
                                // background: 'rgba(76, 174, 79, 0.3)',
                                // boxShadow: 'rgba(53, 95, 54, 0.7) 0px 3px 10px 2px',
                                // // red
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
                        <div
                            style={{
                                position: 'absolute',
                                zIndex: 5,
                                top: `${(rect.top - domPadding - 7 + window.pageYOffset) / domZoom}px`,
                                left: `${(rect.left + rect.width - domPadding - 14 + window.pageXOffset) / domZoom}px`,
                                lineHeight: '14px',
                                padding: '1px 4px',
                                opacity: highlightedElement && highlightedElement !== element ? 0.4 : 1,
                                transition: 'opacity 0.2s, transform 0.2s linear',
                                transform: highlightedElement === element ? 'scale(1.3)' : 'none',
                                color: 'hsla(54, 20%, 12%, 1)',
                                background: '#FFEB3B',
                                boxShadow: 'hsla(54, 100%, 32%, 1) 0px 1px 5px 1px',
                                fontSize: 16,
                                fontWeight: 'bold',
                                fontFamily: 'monospace',
                                pointerEvents: 'none',
                            }}
                        >
                            {index + 1}
                        </div>
                    </React.Fragment>
                )
            })}
        </div>
    )
}
