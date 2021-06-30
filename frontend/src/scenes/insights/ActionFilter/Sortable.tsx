import React from 'react'
import {
    SortableContainer as sortableContainer,
    SortableElement as sortableElement,
    SortableHandle as sortableHandle,
} from 'react-sortable-hoc'
import { SortableDragIcon } from 'lib/components/SortableDragIcon'
import { ActionFilterRow, ActionFilterRowProps } from './ActionFilterRow'

const DragHandle = sortableHandle(() => (
    <span className="action-filter-drag-handle">
        <SortableDragIcon />
    </span>
))

interface SortableActionFilterRowProps extends ActionFilterRowProps {
    filterIndex: number // sortable requires, yet eats, the index prop
}

export const SortableActionFilterRow = sortableElement(
    ({ filterCount, filterIndex, ...props }: SortableActionFilterRowProps) => (
        <div className="draggable-action-filter">
            {filterCount > 1 && <DragHandle />}
            <ActionFilterRow {...props} filterCount={filterCount} index={filterIndex} key={filterIndex} />
        </div>
    )
)

export const SortableContainer = sortableContainer(({ children }: { children: React.ReactNode }) => {
    return <div>{children}</div>
})
