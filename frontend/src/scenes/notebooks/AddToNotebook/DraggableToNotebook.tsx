import React from 'react'
import { NotebookNodeType } from '../Nodes/types'

export type DraggableToNotebookProps = {
    node: NotebookNodeType
    properties: Record<string, any>
    children: React.ReactElement<any>
}

export function DraggableToNotebook({ children, node, properties }: DraggableToNotebookProps): JSX.Element {
    const clonedChild = React.cloneElement(children, {
        draggable: true,
        onDragStart: (e: any) => {
            e.dataTransfer.setData('node', node)
            e.dataTransfer.setData('properties', JSON.stringify(properties))
        },
    })

    return clonedChild
}
