import clsx from 'clsx'
import { DragEventHandler, useState } from 'react'

export function NotebookPopoverDropzone(): JSX.Element {
    const [isDragActive, setIsDragActive] = useState(false)

    const onDrop: DragEventHandler<HTMLDivElement> = (event) => {
        event.preventDefault()
        setIsDragActive(false)

        if (!event.dataTransfer) {
            return null
        }

        const text = event.dataTransfer.getData('text/plain')
        const node = event.dataTransfer.getData('node')
        const properties = event.dataTransfer.getData('properties')
    }
    return (
        <div
            className={clsx('NotebookPopoverDropzone', {
                'NotebookPopoverDropzone--active': isDragActive,
            })}
            onDragEnter={() => setIsDragActive(true)}
            onDragLeave={() => setIsDragActive(false)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
        >
            Drop here for a different Notebook
        </div>
    )
}
