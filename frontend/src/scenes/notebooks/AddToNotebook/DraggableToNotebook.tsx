import React, { useState } from 'react'
import { NotebookNodeType } from '~/types'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import './DraggableToNotebook.scss'
import { useActions } from 'kea'
import { notebookSidebarLogic } from '../Notebook/notebookSidebarLogic'
import clsx from 'clsx'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconJournalPlus } from 'lib/lemon-ui/icons'

export type DraggableToNotebookProps = {
    href?: string
    node?: NotebookNodeType
    properties?: Record<string, any>
    children: React.ReactNode
    alwaysDraggable?: boolean
    noOverflow?: boolean
    className?: string
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
    const { setNotebookSideBarShown } = useActions(notebookSidebarLogic)
    const [isDragging, setIsDragging] = useState(false)
    const keyHeld = useKeyHeld('Alt')

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
                    draggable={draggable}
                    onDragStart={
                        draggable
                            ? (e: any) => {
                                  setIsDragging(true)
                                  if (href) {
                                      const url = window.location.origin + href
                                      e.dataTransfer.setData('text/uri-list', url)
                                      e.dataTransfer.setData('text/plain', url)
                                  }
                                  node && e.dataTransfer.setData('node', node)
                                  properties && e.dataTransfer.setData('properties', JSON.stringify(properties))
                                  setNotebookSideBarShown(true)
                              }
                            : undefined
                    }
                    onDragEnd={() => setIsDragging(false)}
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
