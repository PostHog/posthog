import React from 'react'
import Draggable from 'react-draggable'
import { useActions, useValues } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'

export function ToolbarDraggable({ handle, type, children }) {
    const { defaultPositions } = useValues(dockLogic)
    const { saveDragPosition } = useActions(dockLogic)

    return (
        <Draggable
            handle={handle}
            defaultPosition={defaultPositions[type]}
            onStop={(e, { x, y }) => saveDragPosition(type, x, y)}
        >
            {children}
        </Draggable>
    )
}
