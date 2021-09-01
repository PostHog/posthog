import { useValues } from 'kea'
import React from 'react'
import { elementsLogic } from '../elements/elementsLogic'
import { toursLogic } from './toursLogic'
import { HeatmapElement } from '~/toolbar/elements/HeatmapElement'
import { getBoxColors } from '~/toolbar/utils'

export function ElementSelection(): JSX.Element {
    const { onElementSelection } = useValues(toursLogic)
    const { elementsToDisplay, hoverElement, selectedElement } = useValues(elementsLogic)

    // console.log("ELements", elementsToDisplay)

    return (
        <>
            {onElementSelection && (
                <div
                    style={{
                        textAlign: 'center',
                        color: 'white',
                        position: 'fixed',
                        left: 0,
                        bottom: 0,
                        width: '100%',
                        height: 50,
                        backgroundColor: 'black',
                    }}
                >
                    Select the element where the tooltip should anchor or enter the DOM element
                </div>
            )}
            {elementsToDisplay.map(({ rect, element }, index) => (
                <HeatmapElement
                    key={`inspect-${index}`}
                    rect={rect}
                    style={{
                        pointerEvents: 'all',
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
                    onClick={() => {}}
                    onMouseOver={() => {}}
                    onMouseOut={() => {}}
                />
            ))}
        </>
    )
}
