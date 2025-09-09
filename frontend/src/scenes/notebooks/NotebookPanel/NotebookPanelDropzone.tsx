import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DragEventHandler, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { notebookLogicType } from '../Notebook/notebookLogicType'
import { NotebookSelectList } from '../NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from '../types'
import { notebookPanelLogic } from './notebookPanelLogic'

export function NotebookPanelDropzone(): JSX.Element | null {
    const [isDragActive, setIsDragActive] = useState(false)

    const { dropMode, droppedResource } = useValues(notebookPanelLogic)
    const { setDroppedResource } = useActions(notebookPanelLogic)

    const onDrop: DragEventHandler<HTMLDivElement> = (event) => {
        event.preventDefault()
        setIsDragActive(false)

        if (!event.dataTransfer) {
            return null
        }

        const text = event.dataTransfer.getData('text/plain')
        const node = event.dataTransfer.getData('node')
        const properties = event.dataTransfer.getData('properties')

        setDroppedResource(
            node
                ? {
                      type: node as NotebookNodeType,
                      attrs: properties ? JSON.parse(properties) : {},
                  }
                : text
        )
    }

    const onNotebookOpened = (notebookLogic: notebookLogicType): void => {
        setDroppedResource(null)
        if (droppedResource) {
            typeof droppedResource !== 'string'
                ? notebookLogic.actions.insertAfterLastNode(droppedResource)
                : notebookLogic.actions.pasteAfterLastNode(droppedResource)
        }
    }

    if (!dropMode && !droppedResource) {
        return null
    }

    return (
        <div
            className={clsx('NotebookPanelDropzone', {
                'NotebookPanelDropzone--active': isDragActive,
                'NotebookPanelDropzone--dropped': !!droppedResource,
            })}
            onDragEnter={() => setIsDragActive(true)}
            onDragLeave={() => setIsDragActive(false)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
        >
            {droppedResource ? (
                <div className="NotebookPanelDropzone__dropped">
                    <div className="flex items-start justify-between">
                        <h2>Add dropped resource to...</h2>
                        <LemonButton size="small" onClick={() => setDroppedResource(null)}>
                            Cancel
                        </LemonButton>
                    </div>
                    <NotebookSelectList onNotebookOpened={onNotebookOpened} resource />
                </div>
            ) : (
                <div className="NotebookPanelDropzone__message">Drop here for a different Notebook</div>
            )}
        </div>
    )
}
