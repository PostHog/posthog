import React from 'react'
import {
    SortableContainer as sortableContainer,
    SortableElement as sortableElement,
    SortableHandle as sortableHandle,
} from 'react-sortable-hoc'
import { EllipsisOutlined } from '@ant-design/icons'
import { ActionFilterRow, ActionFilterRowProps } from './ActionFilterRow'

const DragHandle = sortableHandle(() => (
    <span className="action-filter-drag-handle">
        <EllipsisOutlined />
    </span>
))

export const SortableActionFilterRow = sortableElement(({ filterCount, ...props }: ActionFilterRowProps) => (
    <div className="draggable-action-filter">
        {filterCount > 1 && <DragHandle />}
        <ActionFilterRow filterCount={filterCount} {...props} />
    </div>
))

export const SortableContainer = sortableContainer(({ children }: { children: React.ReactNode }) => {
    return <div>{children}</div>
})
