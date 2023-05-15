import React from 'react'
import { NotebookNodeType } from '../Nodes/types'

export type DraggableToNotebookProps = {
    href?: string
    node?: NotebookNodeType
    properties?: Record<string, any>
    children: React.ReactElement<any>
}

export function DraggableToNotebook({ children, node, properties, href }: DraggableToNotebookProps): JSX.Element {
    if (!node && !properties && !href) {
        return children
    }

    const clonedChild = React.cloneElement(children, {
        draggable: true,
        onDragStart: (e: any) => {
            if (href) {
                const url = window.location.origin + href
                e.dataTransfer.setData('text/uri-list', url)
                e.dataTransfer.setData('text/plain', url)
            }
            node && e.dataTransfer.setData('node', node)
            properties && e.dataTransfer.setData('properties', JSON.stringify(properties))
        },
    })

    return clonedChild
}
