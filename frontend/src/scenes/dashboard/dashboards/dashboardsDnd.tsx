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

import { cn } from 'lib/utils/css-classes'

import { dashboardDraggableId, folderDroppableId, parseDashboardDragEnd } from './dashboardsFileSystemUtils'

// Drag-to-folder wiring for the explorer arm: a card is draggable, a folder is droppable,
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
        // The card content is a <Link> (<a>), which the browser drags natively — and which
        // useNotebookDrag additionally marks draggable. That native HTML5 drag suppresses the
        // mousemove stream @dnd-kit's sensors need, so the drop never registers. Cancel it so
        // @dnd-kit owns the gesture for folder moves (a plain click still navigates the link).
        <div ref={setNodeRef} {...attributes} {...listeners} onDragStart={(e) => e.preventDefault()}>
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
        <div ref={setNodeRef} className={cn(className, isOver && 'ring-2 ring-accent rounded')}>
            {children}
        </div>
    )
}
