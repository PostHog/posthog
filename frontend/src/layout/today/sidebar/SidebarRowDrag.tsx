import { useState } from 'react'

import { cn } from '@posthog/quill'

// The rows are links, so this uses the browser's own link drag. A drag from another app or tab has no row value.
const SIDEBAR_ROW_TYPE = 'application/x-posthog-sidebar-row'

/** Lets a row be dragged to a list that takes rows from other lists. */
export function SidebarDragSource({ value, children }: { value: string; children: JSX.Element }): JSX.Element {
    return (
        <div
            onDragStart={(event) => {
                event.dataTransfer.setData(SIDEBAR_ROW_TYPE, value)
                event.dataTransfer.effectAllowed = 'copy'
            }}
        >
            {children}
        </div>
    )
}

/** A list that takes rows dragged from another list. Gets the dropped row's value. */
export function SidebarDropZone({
    onDrop,
    children,
}: {
    onDrop: (value: string) => void
    children: JSX.Element[]
}): JSX.Element {
    const [over, setOver] = useState(false)
    return (
        <div
            onDragOver={(event) => {
                if (!event.dataTransfer.types.includes(SIDEBAR_ROW_TYPE)) {
                    return
                }
                event.preventDefault()
                event.dataTransfer.dropEffect = 'copy'
                setOver(true)
            }}
            onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                    setOver(false)
                }
            }}
            onDrop={(event) => {
                setOver(false)
                const value = event.dataTransfer.getData(SIDEBAR_ROW_TYPE)
                if (value) {
                    // Without this, the browser opens the dropped link.
                    event.preventDefault()
                    onDrop(value)
                }
            }}
            className={cn('flex flex-col gap-px rounded-sm', over && 'bg-fill-button-tertiary-hover ring-2 ring-ring')}
        >
            {children}
        </div>
    )
}
