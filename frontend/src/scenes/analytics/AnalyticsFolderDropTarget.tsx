import { useDndContext, useDroppable } from '@dnd-kit/core'

import { cn } from 'lib/utils/css-classes'

import type { ProjectDragData } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'
import { projectDroppableId } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'
import { isPathUnder } from '~/layout/panel-layout/ProjectTree/utils'

import { ANALYTICS_DRAG_SCOPE } from './analyticsUtils'

/** A folder that takes dropped rows. A folder never takes itself or one of its own parents. */
export function AnalyticsFolderDropTarget({
    path,
    children,
    className,
}: {
    path: string
    children: React.ReactNode
    className?: string
}): JSX.Element {
    const { active } = useDndContext()
    const draggedPath = (active?.data.current as ProjectDragData | undefined)?.identifier.path
    const draggedFolder = (active?.data.current as ProjectDragData | undefined)?.identifier.type === 'folder'
    const disabled = !!draggedPath && draggedFolder && (path === draggedPath || isPathUnder(path, draggedPath))
    const { setNodeRef, isOver } = useDroppable({
        id: projectDroppableId(path, 'project://', ANALYTICS_DRAG_SCOPE),
        disabled,
    })
    return (
        <span
            ref={setNodeRef}
            className={cn(
                'rounded-sm',
                isOver && !disabled && 'bg-fill-button-tertiary-hover ring-2 ring-ring',
                className
            )}
        >
            {children}
        </span>
    )
}
