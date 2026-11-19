import { DndContext, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { cn } from '@posthog/quill'

// A drop ends with a click on the dragged row. dnd-kit stops that click before React sees it, so without this the
// row's link would follow its href and reload the page.
function preventClick(event: MouseEvent): void {
    event.preventDefault()
}

function stopPreventingClick(): void {
    setTimeout(() => window.removeEventListener('click', preventClick, true))
}

function SortableSidebarRow({ value, children }: { value: string; children: JSX.Element }): JSX.Element {
    const { listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: value })
    return (
        <div
            ref={setNodeRef}
            // The row cancels its own pointerdown, and dnd-kit ignores a cancelled event.
            // So the drag listens in the capture phase, before the row cancels the event.
            onPointerDownCapture={(event) => listeners?.onPointerDown?.(event)}
            // The rows are links, and the browser's own link drag would take over from the row drag.
            onDragStart={(event) => event.preventDefault()}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Translate.toString(transform), transition }}
            className={cn('relative', isDragging && 'z-10 opacity-50')}
        >
            {children}
        </div>
    )
}

export function SortableSidebarList<T extends { value: string }>({
    rows,
    renderRow,
    onReorder,
}: {
    rows: T[]
    renderRow: (row: T) => JSX.Element
    onReorder: (fromIndex: number, toIndex: number) => void
}): JSX.Element {
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))
    return (
        <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
            onDragStart={() => window.addEventListener('click', preventClick, true)}
            onDragCancel={stopPreventingClick}
            onDragEnd={({ active, over }) => {
                stopPreventingClick()
                const fromIndex = rows.findIndex((row) => row.value === active.id)
                const toIndex = rows.findIndex((row) => row.value === over?.id)
                if (fromIndex >= 0 && toIndex >= 0 && fromIndex !== toIndex) {
                    onReorder(fromIndex, toIndex)
                }
            }}
        >
            <SortableContext items={rows.map((row) => row.value)} strategy={verticalListSortingStrategy}>
                <div className="flex flex-col gap-px">
                    {rows.map((row) => (
                        <SortableSidebarRow key={row.value} value={row.value}>
                            {renderRow(row)}
                        </SortableSidebarRow>
                    ))}
                </div>
            </SortableContext>
        </DndContext>
    )
}
