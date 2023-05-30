import React from 'react'
import { NotebookNodeType } from '../Nodes/types'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'

export type DraggableToNotebookProps = {
    alwaysDraggable?: boolean
    href?: string
    node?: NotebookNodeType
    properties?: Record<string, any>
    children: React.ReactNode
}

export function DraggableToNotebook({
    children,
    node,
    properties,
    href,
    alwaysDraggable,
}: DraggableToNotebookProps): JSX.Element {
    const keyHeld = useKeyHeld('Alt')

    if (!node && !properties && !href) {
        return <>{children}</>
    }

    return (
        <div
            className="DraggableToNotebook"
            draggable={alwaysDraggable || keyHeld}
            onDragStart={(e: any) => {
                if (href) {
                    const url = window.location.origin + href
                    e.dataTransfer.setData('text/uri-list', url)
                    e.dataTransfer.setData('text/plain', url)
                }
                node && e.dataTransfer.setData('node', node)
                properties && e.dataTransfer.setData('properties', JSON.stringify(properties))
            }}
        >
            {children}
        </div>
    )
}
