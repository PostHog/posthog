import './ActionFilter.scss'
import React, { useEffect } from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { entityFilterLogic, toFilters, LocalFilter } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'
import { PlusCircleOutlined, EllipsisOutlined } from '@ant-design/icons'
import {
    SortableContainer as sortableContainer,
    SortableElement as sortableElement,
    SortableHandle as sortableHandle,
} from 'react-sortable-hoc'
import { alphabet } from 'lib/utils'
import posthog from 'posthog-js'
import { ActionFilter as ActionFilterType, FilterType } from '~/types'

const DragHandle = sortableHandle(() => (
    <span className="action-filter-drag-handle">
        <EllipsisOutlined />
    </span>
))

interface SortableActionFilterRowProps {
    logic: BuiltLogic
    filter: any //TODO
    filterIndex: number
    hideMathSelector?: boolean
    hidePropertySelector?: boolean
    filterCount: number
}

const SortableActionFilterRow = sortableElement(
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
            />
        </div>
    )
)
const SortableContainer = sortableContainer(({ children }: { children: React.ReactNode }) => {
    return <div>{children}</div>
})
export interface ActionFilterProps {
    setFilters: (filters: Record<string, any>) => void
    filters: FilterType
    typeKey: string
    hideMathSelector?: boolean
    hidePropertySelector?: boolean
    copy: string
    disabled?: boolean
    singleFilter?: boolean
    sortable?: boolean
    showLetters?: boolean
    showOr?: boolean
}

export function ActionFilter({
    setFilters,
    filters,
    typeKey,
    hideMathSelector,
    hidePropertySelector = false,
    copy = '',
    disabled = false,
    singleFilter = false,
    sortable = false,
    showLetters = false,
    showOr = false,
}: ActionFilterProps): JSX.Element {
    const logic = entityFilterLogic({ setFilters, filters, typeKey })

    const { localFilters } = useValues(logic)
    const { addFilter, setLocalFilters } = useActions(logic)

    // No way around this. Somehow the ordering of the logic calling each other causes stale "localFilters"
    // to be shown on the /funnels page, even if we try to use a selector with props to hydrate it
    useEffect(() => {
        setLocalFilters(filters)
    }, [filters])

    function onSortEnd({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void {
        function move(arr: LocalFilter[], from: number, to: number): LocalFilter[] {
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
                    <SortableContainer onSortEnd={onSortEnd} lockAxis="y" distance={5}>
                        {localFilters.map((filter, index) => (
                            <SortableActionFilterRow
                                key={index}
                                logic={logic}
                                filter={filter}
                                index={index}
                                filterIndex={index}
                                hideMathSelector={hideMathSelector}
                                hidePropertySelector={hidePropertySelector}
                                filterCount={localFilters.length}
                            />
                        ))}
                    </SortableContainer>
                ) : (
                    localFilters.map((filter, index) => (
                        <ActionFilterRow
                            logic={logic}
                            filter={filter as ActionFilterType}
                            index={index}
                            key={index}
                            letter={showLetters && (alphabet[index] || '-')}
                            hideMathSelector={hideMathSelector}
                            hidePropertySelector={hidePropertySelector}
                            singleFilter={singleFilter}
                            showOr={showOr}
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
