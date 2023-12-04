import './DraggableToNotebook.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React, { useState } from 'react'

import { NotebookNodeType } from '~/types'

import { useNotebookNode } from '../Nodes/NotebookNodeContext'
import { notebookPanelLogic } from '../NotebookPanel/notebookPanelLogic'

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
    const { featureFlags } = useValues(featureFlagLogic)

    const notebooksEnabled = featureFlags[FEATURE_FLAGS.NOTEBOOKS]
    const isInNotebook = useNotebookNode()
    const hasDragOptions = !!(href || node)

    const altKeyHeld = useKeyHeld('Alt')
    const dragModeActive = onlyWithModifierKey ? altKeyHeld : true

    if (!hasDragOptions || isInNotebook || !notebooksEnabled || !dragModeActive) {
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
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} fallback={children}>
                <span
                    className={clsx('DraggableToNotebook', className, isDragging && 'DraggableToNotebook--dragging')}
                    draggable={draggable}
                    {...elementProps}
                >
                    {children}
                </span>
            </FlaggedFeature>
        </>
    )
}
