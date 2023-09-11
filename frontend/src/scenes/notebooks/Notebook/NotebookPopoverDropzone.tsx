import clsx from 'clsx'
import { DragEventHandler, useState } from 'react'
import { notebookPopoverLogic } from './notebookPopoverLogic'
import { useActions, useValues } from 'kea'
import { NotebookNodeType } from '~/types'
import { NotebookSelectList } from '../NotebookSelectButton/NotebookSelectButton'

export function NotebookPopoverDropzone(): JSX.Element | null {
    const [isDragActive, setIsDragActive] = useState(false)

    const { dropMode, droppedResource } = useValues(notebookPopoverLogic)
    const { setDroppedResource } = useActions(notebookPopoverLogic)

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

    if (!dropMode && !droppedResource) {
        return null
    }

    return (
        <div
            className={clsx('NotebookPopoverDropzone', {
                'NotebookPopoverDropzone--active': isDragActive,
                'NotebookPopoverDropzone--dropped': !!droppedResource,
            })}
            onDragEnter={() => setIsDragActive(true)}
            onDragLeave={() => setIsDragActive(false)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
        >
            {droppedResource ? (
                <div className="NotebookPopoverDropzone__dropped">
                    <h2>Add dropped resource to...</h2>
                    <NotebookSelectList />
                </div>
            ) : (
                <div className="NotebookPopoverDropzone__message">Drop here for a different Notebook</div>
            )}
        </div>
    )
}
