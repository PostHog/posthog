import { useActions, useValues } from 'kea'
import type { DragEvent, ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import {
    BIShelf,
    BI_FIELD_DRAG_MIME_TYPE,
    BI_SHELF_PILL_DRAG_MIME_TYPE,
    getBIDropTarget,
    parseBIField,
    parseBIShelfPillDragData,
} from 'products/business_intelligence/frontend/biEditorTypes'

function carriesBIDrag(event: DragEvent<HTMLElement>): 'field' | 'pill' | null {
    const types = Array.from(event.dataTransfer.types)
    return types.includes(BI_SHELF_PILL_DRAG_MIME_TYPE)
        ? 'pill'
        : types.includes(BI_FIELD_DRAG_MIME_TYPE)
          ? 'field'
          : null
}

/** Accepts fields from the data pane or the database tree, and pills moved from other shelves. */
export function BIShelfDropTarget({
    shelf,
    className,
    children,
}: {
    shelf: BIShelf
    className?: string
    children: ReactNode
}): JSX.Element {
    const { activeDropShelf, dragSessionId } = useValues(biEditorLogic)
    const { addFieldToShelf, clearActiveDropShelf, moveFieldToShelf, setActiveDropShelf } = useActions(biEditorLogic)

    return (
        <div
            className={cn(
                'rounded transition-colors',
                activeDropShelf === shelf && 'bg-accent-highlight-secondary ring-2 ring-inset ring-accent',
                className
            )}
            data-attr={`bi-editor-${shelf}-shelf`}
            onDragEnter={(event) => {
                if (carriesBIDrag(event)) {
                    setActiveDropShelf(shelf)
                }
            }}
            onDragOver={(event) => {
                const dragKind = carriesBIDrag(event)
                if (dragKind) {
                    event.preventDefault()
                    event.dataTransfer.dropEffect = dragKind === 'pill' ? 'move' : 'copy'
                }
            }}
            onDragLeave={(event) => {
                const nextTarget = event.relatedTarget
                if (!nextTarget || !event.currentTarget.contains(nextTarget as Node)) {
                    clearActiveDropShelf(shelf)
                }
            }}
            onDrop={(event) => {
                event.preventDefault()
                event.stopPropagation()
                clearActiveDropShelf(shelf)
                const pill = parseBIShelfPillDragData(event.dataTransfer.getData(BI_SHELF_PILL_DRAG_MIME_TYPE))
                if (pill) {
                    if (pill.dragSessionId !== dragSessionId) {
                        return
                    }
                    // Measures sit on the rows strip, so dropping one on rows or columns keeps it a measure
                    const keepsMeasure = pill.shelf === 'values' && (shelf === 'rows' || shelf === 'columns')
                    if (!keepsMeasure) {
                        moveFieldToShelf(pill.shelf, pill.index, shelf)
                    }
                    return
                }
                const field = parseBIField(event.dataTransfer.getData(BI_FIELD_DRAG_MIME_TYPE))
                if (field) {
                    const target = getBIDropTarget(field, shelf)
                    addFieldToShelf(target.field, target.shelf)
                }
            }}
        >
            {children}
        </div>
    )
}
