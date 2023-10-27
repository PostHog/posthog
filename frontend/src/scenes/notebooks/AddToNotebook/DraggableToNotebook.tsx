import React, { useState } from 'react'
import { NotebookNodeType } from '~/types'
import './DraggableToNotebook.scss'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useNotebookNode } from '../Nodes/notebookNodeLogic'
import { notebookPanelLogic } from '../NotebookPanel/notebookPanelLogic'

export type DraggableToNotebookBaseProps = {
    href?: string
    node?: NotebookNodeType
    properties?: Record<string, any>
}

export type DraggableToNotebookProps = DraggableToNotebookBaseProps & {
    children: React.ReactNode
    className?: string
}

export function useNotebookDrag({ href, node, properties }: DraggableToNotebookBaseProps): {
    isDragging: boolean
    elementProps: Pick<React.HTMLAttributes<HTMLElement>, 'draggable' | 'onDragStart' | 'onDragEnd'>
} {
    const { startDropMode, endDropMode } = useActions(notebookPanelLogic)

    const [isDragging, setIsDragging] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)

    const notebooksEnabled = featureFlags[FEATURE_FLAGS.NOTEBOOKS]
    const isInNotebook = useNotebookNode()
    const hasDragOptions = !!(href || node)

    if (!hasDragOptions || isInNotebook || !notebooksEnabled) {
        return {
            isDragging: false,
            elementProps: {},
        }
    }

    return {
        isDragging,
        elementProps: {
            draggable: true,
            onDragStart: (e: any) => {
                setIsDragging(true)
                startDropMode()
                if (href) {
                    const url = window.location.origin + href
                    e.dataTransfer.setData('text/uri-list', url)
                    e.dataTransfer.setData('text/plain', url)
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
}: DraggableToNotebookProps): JSX.Element {
    const { isDragging, elementProps } = useNotebookDrag({ href, node, properties })

    if (!node && !properties && !href) {
        return <>{children}</>
    }

    return (
        <>
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} fallback={children}>
                <span
                    className={clsx('DraggableToNotebook', className, isDragging && 'DraggableToNotebook--dragging')}
                    {...elementProps}
                >
                    {children}
                </span>
            </FlaggedFeature>
        </>
    )
}
