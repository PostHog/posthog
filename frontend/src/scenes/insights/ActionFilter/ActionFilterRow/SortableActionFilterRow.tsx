import React from 'react'
import { SortableContainer as sortableContainer, SortableElement as sortableElement } from 'react-sortable-hoc'
import { ActionFilterRow, ActionFilterRowProps } from './ActionFilterRow'

interface SortableActionFilterRowProps extends ActionFilterRowProps {
    filterIndex: number // sortable requires, yet eats, the index prop
}

export const SortableActionFilterRow = sortableElement(
    ({ filterCount, filterIndex, ...props }: SortableActionFilterRowProps) => {
        return <ActionFilterRow {...props} filterCount={filterCount} index={filterIndex} key={filterIndex} />
    }
)

export const SortableActionFilterContainer = sortableContainer(({ children }: { children: React.ReactNode }) => {
    return <div>{children}</div>
})
