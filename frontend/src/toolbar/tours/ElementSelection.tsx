import { useValues } from 'kea'
import React from 'react'
import { toursLogic } from './toursLogic'

export function ElementSelection(): JSX.Element {
    const { onElementSelection } = useValues(toursLogic)

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
        </>
    )
}
