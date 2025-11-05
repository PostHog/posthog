import './DraggableToNotebook.scss'

import clsx from 'clsx'
import React from 'react'

import { useDraggableLink } from 'lib/components/DraggableLink/useDraggableLink'

import { NotebookNodeType } from '../types'

export type DraggableToNotebookBaseProps = {
    href?: string
    node?: NotebookNodeType
    properties?: Record<string, any>
    onlyWithModifierKey?: boolean
}

export type DraggableToNotebookProps = DraggableToNotebookBaseProps & {
    children: React.ReactNode
    className?: string
}

export function useNotebookDrag({ href, node, properties, onlyWithModifierKey }: DraggableToNotebookBaseProps): {
    isDragging: boolean
    draggable: boolean
    elementProps: Pick<React.HTMLAttributes<HTMLElement>, 'onDragStart' | 'onDragEnd'>
} {
    // For now, delegate to the general draggable link system for href-based drags
    // Node-based drags (notebooks) still use the original system
    const linkDrag = useDraggableLink({
        href: href,
        properties: { ...properties, node },
        onlyWithModifierKey,
    })

    // If we have a node but no href, we need special notebook handling
    // For now, return the link drag result since most use cases are href-based
    return linkDrag
}

export function DraggableToNotebook({
    children,
    node,
    properties,
    href,
    className,
    onlyWithModifierKey,
}: DraggableToNotebookProps): JSX.Element {
    const { isDragging, draggable, elementProps } = useNotebookDrag({ href, node, properties, onlyWithModifierKey })

    if (!node && !properties && !href) {
        return <>{children}</>
    }

    return (
        <>
            <span
                className={clsx('DraggableToNotebook', className, isDragging && 'DraggableToNotebook--dragging')}
                draggable={draggable}
                {...elementProps}
            >
                {children}
            </span>
        </>
    )
}
