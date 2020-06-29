import React from 'react'
import { ToolbarButton } from '~/toolbar/button/ToolbarButton'
import Draggable from 'react-draggable'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { useActions, useValues } from 'kea'

export function DraggableButton({ showInvisibleButton }) {
    const { dragPosition } = useValues(toolbarButtonLogic)
    const { saveDragPosition } = useActions(toolbarButtonLogic)
    return (
        <Draggable
            handle="#button-toolbar"
            position={dragPosition}
            onDrag={(e, { x, y }) => saveDragPosition(x, y)}
            onStop={(e, { x, y }) => saveDragPosition(x, y)}
        >
            <div id="button-toolbar" className={showInvisibleButton ? 'toolbar-invisible' : ''}>
                <ToolbarButton />
            </div>
        </Draggable>
    )
}
