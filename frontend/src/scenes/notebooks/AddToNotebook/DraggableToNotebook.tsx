import React, { useState } from 'react'
import { NotebookNodeType } from '~/types'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import './DraggableToNotebook.scss'
import { useActions, useValues } from 'kea'
import { notebookPopoverLogic } from '../Notebook/notebookPopoverLogic'
import clsx from 'clsx'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconJournalPlus } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export type DraggableToNotebookBaseProps = {
    href?: string
    node?: NotebookNodeType
    properties?: Record<string, any>
}

export type DraggableToNotebookProps = DraggableToNotebookBaseProps & {
    children: React.ReactNode
    alwaysDraggable?: boolean
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

    if (!href && !node && !properties) {
        return {
            isDragging: false,
            elementProps: {},
        }
    }

    if (!notebooksEnabled) {
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
    alwaysDraggable,
    noOverflow,
    className,
}: DraggableToNotebookProps): JSX.Element {
    const keyHeld = useKeyHeld('Alt')
    const { isDragging, elementProps } = useNotebookDrag({ href, node, properties })

    if (!node && !properties && !href) {
        return <>{children}</>
    }

    const draggable = alwaysDraggable || keyHeld

    return (
        <>
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} fallback={children}>
                <span
                    className={clsx(
                        'DraggableToNotebook',
                        className,
                        noOverflow && 'DraggableToNotebook--no-overflow',
                        keyHeld && 'DraggableToNotebook--highlighted',
                        isDragging && 'DraggableToNotebook--dragging'
                    )}
                    {...elementProps}
                    draggable={draggable}
                >
                    {keyHeld ? (
                        <div className="DraggableToNotebook__highlighter">
                            <div className="DraggableToNotebook__highlighter__info">
                                <span className="DraggableToNotebook__highlighter__info__text">Drag to notebook</span>
                                <IconJournalPlus className="text-lg" />
                            </div>
                        </div>
                    ) : null}
                    {children}
                </span>
            </FlaggedFeature>
        </>
    )
}
