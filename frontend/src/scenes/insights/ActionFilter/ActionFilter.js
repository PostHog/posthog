import './ActionFilter.scss'
import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic, toFilters } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'
import { PlusCircleOutlined, EllipsisOutlined } from '@ant-design/icons'
import { sortableContainer, sortableElement, sortableHandle } from 'react-sortable-hoc'
import posthog from 'posthog-js'

const DragHandle = sortableHandle(() => (
    <span className="action-filter-drag-handle">
        <EllipsisOutlined />
    </span>
))
const SortableActionFilterRow = sortableElement(({ logic, filter, filterIndex, hideMathSelector, filterCount }) => (
    <div className="draggable-action-filter">
        {filterCount > 1 && <DragHandle />}
        <ActionFilterRow
            logic={logic}
            filter={filter}
            // sortableElement requires, yet eats the index prop, so passing via filterIndex here
            index={filterIndex}
            key={filterIndex}
            hideMathSelector={hideMathSelector}
        />
    </div>
))
const SortableContainer = sortableContainer(({ children }) => {
    return <div>{children}</div>
})

export function ActionFilter({
    setFilters,
    filters,
    typeKey,
    hideMathSelector,
    copy = '',
    disabled = false,
    singleFilter = false,
    sortable = false,
}) {
    const logic = entityFilterLogic({ setFilters, filters, typeKey })

    const { localFilters } = useValues(logic)
    const { addFilter, setLocalFilters } = useActions(logic)

    // No way around this. Somehow the ordering of the logic calling each other causes stale "localFilters"
    // to be shown on the /funnels page, even if we try to use a selector with props to hydrate it
    useEffect(() => {
        setLocalFilters(filters)
    }, [filters])

    function onSortEnd({ oldIndex, newIndex }) {
        const move = (arr, from, to) => {
            const clone = [...arr]
            Array.prototype.splice.call(clone, to, 0, Array.prototype.splice.call(clone, from, 1)[0])
            return clone.map((child, order) => ({ ...child, order }))
        }
        setFilters(toFilters(move(localFilters, oldIndex, newIndex)))
        if (oldIndex !== newIndex) {
            posthog.capture('funnel step reordered')
        }
    }

    return (
        <div>
            {localFilters ? (
                sortable ? (
                    <SortableContainer onSortEnd={onSortEnd} useDragHandle lockAxis="y">
                        {localFilters.map((filter, index) => (
                            <SortableActionFilterRow
                                key={index}
                                logic={logic}
                                filter={filter}
                                index={index}
                                filterIndex={index}
                                hideMathSelector={hideMathSelector}
                                filterCount={localFilters.length}
                            />
                        ))}
                    </SortableContainer>
                ) : (
                    localFilters.map((filter, index) => (
                        <ActionFilterRow
                            logic={logic}
                            filter={filter}
                            index={index}
                            key={index}
                            hideMathSelector={hideMathSelector}
                            singleFilter={singleFilter}
                        />
                    ))
                )
            ) : null}
            {!singleFilter && (
                <div className="mt">
                    <Button
                        type="primary"
                        onClick={() => addFilter()}
                        style={{ marginTop: '0.5rem' }}
                        data-attr="add-action-event-button"
                        icon={<PlusCircleOutlined />}
                        disabled={disabled}
                    >
                        {copy || 'Action or event'}
                    </Button>
                </div>
            )}
        </div>
    )
}
