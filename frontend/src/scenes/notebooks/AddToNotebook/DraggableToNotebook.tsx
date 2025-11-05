import './DraggableToNotebook.scss'

import clsx from 'clsx'
import { useActions } from 'kea'
import React, { useState } from 'react'

import { useKeyHeld } from 'lib/hooks/useKeyHeld'

import { useNotebookNode } from '../Nodes/NotebookNodeContext'
import { notebookPanelLogic } from '../NotebookPanel/notebookPanelLogic'
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
    const { startDropMode, endDropMode } = useActions(notebookPanelLogic)

    const [isDragging, setIsDragging] = useState(false)

    const isInNotebook = useNotebookNode()
    const hasDragOptions = !!(href || node)

    const altKeyHeld = useKeyHeld('Alt')
    const dragModeActive = onlyWithModifierKey ? altKeyHeld : true

    if (!hasDragOptions || isInNotebook || !dragModeActive) {
        return {
            isDragging: false,
            draggable: false,
            elementProps: {},
        }
    }

    return {
        isDragging,
        draggable: true,
        elementProps: {
            onDragStart: (e: any) => {
                setIsDragging(true)
                startDropMode()
                if (href) {
                    const url = window.location.origin + href
                    e.dataTransfer.setData('text/uri-list', url)
                    e.dataTransfer.setData('text/plain', url)
                    // Add data for shortcuts
                    e.dataTransfer.setData('text/href', href)
                    e.dataTransfer.setData('text/title', e.currentTarget?.textContent || '')
                }
                node && e.dataTransfer.setData('node', node)
                properties && e.dataTransfer.setData('properties', JSON.stringify(properties))
            },
            onDragEnd: () => {
                setIsDragging(false)
                endDropMode()
            },
        },
    }
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
