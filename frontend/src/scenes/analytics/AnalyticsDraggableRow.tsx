import { useDraggable } from '@dnd-kit/core'
import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { ProjectDragData } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { ANALYTICS_DRAG_SCOPE } from './analyticsUtils'

/**
 * Lets a list row be dragged onto a folder. The app-wide project drag context performs the move,
 * so the row is handed to the project tree first: that context only resolves rows the tree knows.
 */
export function AnalyticsDraggableRow({
    entry,
    children,
}: {
    entry: FileSystemEntry
    children: React.ReactNode
}): JSX.Element {
    const { createSavedItem } = useActions(projectTreeDataLogic)
    const data: ProjectDragData = {
        identifier: { type: entry.type, ref: entry.ref, href: entry.href, path: entry.path },
        logicKey: ANALYTICS_DRAG_SCOPE,
    }
    const { listeners, setNodeRef, isDragging } = useDraggable({ id: `${ANALYTICS_DRAG_SCOPE}::${entry.id}`, data })
    // A drop ends with a click on whatever sits under the pointer, which must not open the dragged row.
    const dragged = useRef(false)
    useEffect(() => {
        if (isDragging) {
            dragged.current = true
        }
    }, [isDragging])

    return (
        <span
            ref={setNodeRef}
            {...listeners}
            onPointerDownCapture={() => createSavedItem(entry)}
            // The browser's own link drag would take over from the row drag.
            onDragStart={(event) => event.preventDefault()}
            onClickCapture={(event) => {
                if (dragged.current) {
                    dragged.current = false
                    event.preventDefault()
                    event.stopPropagation()
                }
            }}
            className={cn('flex min-w-0 flex-1 items-center gap-2 overflow-hidden', isDragging && 'opacity-50')}
        >
            {children}
        </span>
    )
}
