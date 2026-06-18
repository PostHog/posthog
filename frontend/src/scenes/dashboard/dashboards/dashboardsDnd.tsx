import {
    DndContext,
    DragEndEvent,
    MouseSensor,
    TouchSensor,
    useDraggable,
    useDroppable,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { ReactNode } from 'react'

import { dashboardDraggableId, folderDroppableId, parseDashboardDragEnd } from './dashboardsFileSystemUtils'

// Shared drag-to-folder wiring for the grid and finder arms: a card is draggable, a folder is droppable,
// and dropping resolves to onMove(dashboardId, folder). The 10px mouse activation distance keeps a plain
// click a navigation/open and a longer movement a drag.
export function DashboardsDndContext({
    onMove,
    children,
}: {
    onMove: (dashboardId: number, folder: string) => void
    children: ReactNode
}): JSX.Element {
    const mouseSensor = useSensor(MouseSensor, { activationConstraint: { distance: 10 } })
    const touchSensor = useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } })
    const sensors = useSensors(mouseSensor, touchSensor)

    const onDragEnd = (event: DragEndEvent): void => {
        const move = parseDashboardDragEnd(event.active?.id, event.over?.id)
        if (move) {
            onMove(move.dashboardId, move.folder)
        }
    }

    return (
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
            {children}
        </DndContext>
    )
}

export function DraggableDashboard({
    dashboardId,
    children,
}: {
    dashboardId: number
    children: ReactNode
}): JSX.Element {
    const { attributes, listeners, setNodeRef } = useDraggable({ id: dashboardDraggableId(dashboardId) })
    return (
        <div ref={setNodeRef} {...attributes} {...listeners}>
            {children}
        </div>
    )
}

export function DroppableFolder({
    folder,
    className,
    children,
}: {
    folder: string
    className?: string
    children: ReactNode
}): JSX.Element {
    const { setNodeRef, isOver } = useDroppable({ id: folderDroppableId(folder) })
    return (
        <div ref={setNodeRef} className={isOver ? `${className ?? ''} ring-2 ring-accent rounded` : className}>
            {children}
        </div>
    )
}
