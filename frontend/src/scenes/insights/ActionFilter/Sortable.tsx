import React from 'react'
import {
    SortableContainer as sortableContainer,
    SortableElement as sortableElement,
    SortableHandle as sortableHandle,
} from 'react-sortable-hoc'
import { EllipsisOutlined } from '@ant-design/icons'
import { entityFilterLogic } from './entityFilterLogic'
import { ActionFilter } from '~/types'
import { ActionFilterRow } from './ActionFilterRow'

const DragHandle = sortableHandle(() => (
    <span className="action-filter-drag-handle">
        <EllipsisOutlined />
    </span>
))

interface SortableActionFilterRowProps {
    logic: typeof entityFilterLogic
    filter: ActionFilter
    filterIndex: number
    hideMathSelector?: boolean
    hidePropertySelector?: boolean
    filterCount: number
}

export const SortableActionFilterRow = sortableElement(
    ({
        logic,
        filter,
        filterIndex,
        hideMathSelector,
        hidePropertySelector,
        filterCount,
    }: SortableActionFilterRowProps) => (
        <div className="draggable-action-filter">
            {filterCount > 1 && <DragHandle />}
            <ActionFilterRow
                logic={logic}
                filter={filter}
                // sortableElement requires, yet eats the index prop, so passing via filterIndex here
                index={filterIndex}
                key={filterIndex}
                hideMathSelector={hideMathSelector}
                hidePropertySelector={hidePropertySelector}
                filterCount={filterCount}
            />
        </div>
    )
)

export const SortableContainer = sortableContainer(({ children }: { children: React.ReactNode }) => {
    return <div>{children}</div>
})
