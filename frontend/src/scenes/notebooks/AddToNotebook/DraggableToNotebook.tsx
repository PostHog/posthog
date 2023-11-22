import './DraggableToNotebook.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React, { useState } from 'react'

import { NotebookNodeType } from '~/types'

import { useNotebookNode } from '../Nodes/NotebookNodeContext'
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
    elementProps: Pick<React.HTMLAttributes<HTMLElement>, 'onDragStart' | 'onDragEnd'>
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
                    draggable={elementProps.onDragEnd ? true : false}
                    {...elementProps}
                >
                    {children}
                </span>
            </FlaggedFeature>
        </>
    )
}
