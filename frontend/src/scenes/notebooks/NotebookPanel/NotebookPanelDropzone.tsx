import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DragEventHandler, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { draggableLinkLogic } from 'lib/components/DraggableLink/draggableLinkLogic'

import { notebookLogicType } from '../Notebook/notebookLogicType'
import { NotebookSelectList } from '../NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeResource, NotebookNodeType } from '../types'
import { notebookPanelLogic } from './notebookPanelLogic'

export function NotebookPanelDropzone(): JSX.Element | null {
    const [isDragActive, setIsDragActive] = useState(false)

    const { dropMode } = useValues(draggableLinkLogic)
    const { notebookDroppedResource } = useValues(notebookPanelLogic)
    const { setDroppedResource } = useActions(draggableLinkLogic)
    const { setNotebookDroppedResource } = useActions(notebookPanelLogic)

    const onDrop: DragEventHandler<HTMLDivElement> = (event) => {
        event.preventDefault()
        setIsDragActive(false)

        if (!event.dataTransfer) {
            return null
        }

        const text = event.dataTransfer.getData('text/plain')
        const node = event.dataTransfer.getData('node')
        const properties = event.dataTransfer.getData('properties')

        const resource: NotebookNodeResource | string = node
            ? {
                  type: node as NotebookNodeType,
                  attrs: properties ? JSON.parse(properties) : {},
              }
            : text

        setDroppedResource(typeof resource === 'string' ? resource : null)
        setNotebookDroppedResource(resource)
    }

    const onNotebookOpened = (notebookLogic: notebookLogicType): void => {
        setDroppedResource(null)
        setNotebookDroppedResource(null)
        if (notebookDroppedResource) {
            typeof notebookDroppedResource !== 'string'
                ? notebookLogic.actions.insertAfterLastNode(notebookDroppedResource)
                : notebookLogic.actions.pasteAfterLastNode(notebookDroppedResource)
        }
    }

    if (!dropMode && !notebookDroppedResource) {
        return null
    }

    return (
        <div
            className={clsx('NotebookPanelDropzone', {
                'NotebookPanelDropzone--active': isDragActive,
                'NotebookPanelDropzone--dropped': !!notebookDroppedResource,
            })}
            onDragEnter={() => setIsDragActive(true)}
            onDragLeave={() => setIsDragActive(false)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
        >
            {notebookDroppedResource ? (
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
