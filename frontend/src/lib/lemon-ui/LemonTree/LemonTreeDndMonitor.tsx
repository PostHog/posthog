import { DndContextProps, useDndMonitor } from '@dnd-kit/core'
import { ReactNode } from 'react'

export function LemonTreeDndMonitor({
    scope,
    children,
    onDragStart,
    onDragOver,
    onDragEnd,
    onDragCancel,
}: DndContextProps & { scope: string; children: ReactNode }): JSX.Element {
    useDndMonitor({
        onDragStart: (event) => {
            if (event.active.data.current?.treeScope === scope) {
                onDragStart?.({ ...event, active: { ...event.active, id: event.active.data.current.treeId } })
            }
        },
        onDragOver: (event) => {
            if (event.active.data.current?.treeScope === scope) {
                onDragOver?.(event)
            }
        },
        onDragEnd: (event) => {
            if (event.active.data.current?.treeScope === scope) {
                onDragEnd?.({
                    ...event,
                    active: { ...event.active, id: event.active.data.current.treeId },
                    over: event.over?.data.current ? { ...event.over, id: event.over.data.current.treeId } : null,
                })
            }
        },
        onDragCancel: (event) => {
            if (event.active.data.current?.treeScope === scope) {
                onDragCancel?.(event)
            }
        },
    })
    return <>{children}</>
}
