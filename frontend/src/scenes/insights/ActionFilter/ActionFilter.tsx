import './ActionFilter.scss'
import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic, toFilters, LocalFilter } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'
import { PlusCircleOutlined } from '@ant-design/icons'
import { alphabet } from 'lib/utils'
import posthog from 'posthog-js'
import { ActionFilter as ActionFilterType, FilterType, Optional } from '~/types'
import { SortableContainer, SortableActionFilterRow } from './Sortable'

export interface ActionFilterProps {
    setFilters: (filters: FilterType) => void
    filters: Optional<FilterType, 'type'>
    typeKey: string
    hideMathSelector?: boolean
    hidePropertySelector?: boolean
    buttonCopy: string
    disabled?: boolean
    singleFilter?: boolean
    sortable?: boolean
    showLetters?: boolean
    showOr?: boolean
    verbose?: boolean
}

export function ActionFilter({
    setFilters,
    filters,
    typeKey,
    hideMathSelector,
    hidePropertySelector = false,
    buttonCopy = '',
    disabled = false,
    singleFilter = false,
    sortable = false,
    showLetters = false,
    showOr = false,
    verbose = false,
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
                                logic={logic as any}
                                filter={filter as ActionFilterType}
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
                            logic={logic as any}
                            filter={filter as ActionFilterType}
                            index={index}
                            key={index}
                            letter={(showLetters && (alphabet[index] || '-')) || null}
                            hideMathSelector={hideMathSelector}
                            hidePropertySelector={hidePropertySelector}
                            singleFilter={singleFilter}
                            showOr={showOr}
                            verbose={verbose}
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
                        {buttonCopy || 'Action or event'}
                    </Button>
                </div>
            )}
        </div>
    )
}
