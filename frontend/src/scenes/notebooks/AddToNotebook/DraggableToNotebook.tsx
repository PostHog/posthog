import React, { useState } from 'react'
import { NotebookNodeType } from '~/types'
import './DraggableToNotebook.scss'
import { useActions, useValues } from 'kea'
import { notebookPopoverLogic } from '../Notebook/notebookPopoverLogic'
import clsx from 'clsx'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useNotebookNode } from '../Nodes/notebookNodeLogic'

export type DraggableToNotebookBaseProps = {
    href?: string
    node?: NotebookNodeType
    properties?: Record<string, any>
}

export type DraggableToNotebookProps = DraggableToNotebookBaseProps & {
    children: React.ReactNode
    noOverflow?: boolean
    className?: string
}

export function useNotebookDrag({ href, node, properties }: DraggableToNotebookBaseProps): {
    isDragging: boolean
    elementProps: Pick<React.HTMLAttributes<HTMLElement>, 'draggable' | 'onDragStart' | 'onDragEnd'>
} {
    const { setVisibility } = useActions(notebookPopoverLogic)
    const { visibility } = useValues(notebookPopoverLogic)
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
                if (visibility !== 'visible') {
                    setVisibility('peek')
                }
                if (href) {
                    const url = window.location.origin + href
                    e.dataTransfer.setData('text/uri-list', url)
                    e.dataTransfer.setData('text/plain', url)
                }
                node && e.dataTransfer.setData('node', node)
                properties && e.dataTransfer.setData('properties', JSON.stringify(properties))
                setVisibility('peek')
            },
            onDragEnd: () => {
                setIsDragging(false)
                if (visibility !== 'visible') {
                    setVisibility('hidden')
                }
            },
        },
    }
}

export function DraggableToNotebook({
    children,
    node,
    properties,
    href,
    noOverflow,
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
                    className={clsx(
                        'DraggableToNotebook',
                        className,
                        noOverflow && 'DraggableToNotebook--no-overflow',
                        isDragging && 'DraggableToNotebook--dragging'
                    )}
                    {...elementProps}
                >
                    {children}
                </span>
            </FlaggedFeature>
        </>
    )
}
