import React from 'react'
import { NotebookNodeType } from '../Nodes/types'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import './DraggableToNotebook.scss'
import { useActions, useValues } from 'kea'
import { notebookSidebarLogic } from '../Notebook/notebookSidebarLogic'
import clsx from 'clsx'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

export type DraggableToNotebookProps = {
    href?: string
    node?: NotebookNodeType
    properties?: Record<string, any>
    children: React.ReactNode
    alwaysDraggable?: boolean
    noOverflow?: boolean
}

function DraggableToNotebookIndicator(): JSX.Element {
    return (
        <div className="DraggableToNotebookIndicator">
            <div className="DraggableToNotebookIndicator__pulser" />
        </div>
    )
}

export function DraggableToNotebook({
    children,
    node,
    properties,
    href,
    alwaysDraggable,
    noOverflow,
}: DraggableToNotebookProps): JSX.Element {
    const { notebookSideBarShown } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown } = useActions(notebookSidebarLogic)
    const keyHeld = useKeyHeld('Alt')

    if (!node && !properties && !href) {
        return <>{children}</>
    }

    return (
        <>
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} match={false}>
                {children}
            </FlaggedFeature>
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} match>
                <div
                    className={clsx('DraggableToNotebook', noOverflow && 'DraggableToNotebook--no-overflow')}
                    draggable={alwaysDraggable || keyHeld}
                    onDragStart={(e: any) => {
                        if (href) {
                            const url = window.location.origin + href
                            e.dataTransfer.setData('text/uri-list', url)
                            e.dataTransfer.setData('text/plain', url)
                        }
                        node && e.dataTransfer.setData('node', node)
                        properties && e.dataTransfer.setData('properties', JSON.stringify(properties))
                        setNotebookSideBarShown(true)
                    }}
                >
                    {keyHeld ? <DraggableToNotebookIndicator /> : null}
                    {children}
                </div>
            </FlaggedFeature>
        </>
    )
}
