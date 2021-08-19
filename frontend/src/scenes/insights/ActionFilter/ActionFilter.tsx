import './ActionFilter.scss'
import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic, toFilters, LocalFilter } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow/ActionFilterRow'
import { Button } from 'antd'
import { PlusCircleOutlined } from '@ant-design/icons'
import posthog from 'posthog-js'
import { ActionFilter as ActionFilterType, FilterType, Optional } from '~/types'
import { SortableContainer, SortableActionFilterRow } from './Sortable'

export interface ActionFilterProps {
    setFilters: (filters: FilterType) => void
    filters: Optional<FilterType, 'type'>
    typeKey: string
    hideMathSelector?: boolean
    hidePropertySelector?: boolean
    buttonCopy: string // Text copy for the action button to add more events/actions (graph series)
    disabled?: boolean // Whether the full control is enabled or not
    singleFilter?: boolean // Whether it's allowed to add multiple event/action series (e.g. lifecycle only accepts one event)
    sortable?: boolean // Whether actions/events can be sorted (used mainly for funnel step reordering)
    showSeriesIndicator?: boolean // Whether to show an indicator identifying each graph
    seriesIndicatorType?: 'alpha' | 'numeric' // Series badge shows A, B, C | 1, 2, 3
    showOr?: boolean // Whether to show the "OR" label after each filter
    hideFilter?: boolean // Hide local filtering (currently used for retention insight)
    customRowPrefix?: string | JSX.Element // Custom prefix element to show in each ActionFilterRow
    customActions?: JSX.Element // Custom actions to be added next to the add series button
    horizontalUI?: boolean
    fullWidth?: boolean
    showNestedArrow?: boolean // show nested arrows to the left of property filter buttons
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
    showSeriesIndicator = false,
    seriesIndicatorType = 'alpha',
    showOr = false,
    hideFilter = false,
    horizontalUI = false,
    fullWidth = false,
    customRowPrefix,
    customActions,
    showNestedArrow = false,
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

    const commonProps = {
        logic: logic as any,
        showSeriesIndicator,
        seriesIndicatorType,
        hideMathSelector,
        hidePropertySelector,
        customRowPrefix,
        hasBreakdown: !!filters.breakdown,
        fullWidth,
    }

    return (
        <div>
            {localFilters ? (
                sortable ? (
                    <SortableContainer onSortEnd={onSortEnd} lockAxis="y" distance={5}>
                        {localFilters.map((filter, index) => (
                            <SortableActionFilterRow
                                key={index}
                                filter={filter as ActionFilterType}
                                index={index}
                                filterIndex={index}
                                filterCount={localFilters.length}
                                showNestedArrow={showNestedArrow}
                                {...commonProps}
                            />
                        ))}
                    </SortableContainer>
                ) : (
                    localFilters.map((filter, index) => (
                        <ActionFilterRow
                            filter={filter as ActionFilterType}
                            index={index}
                            key={index}
                            singleFilter={singleFilter}
                            showOr={showOr}
                            hideFilter={hideFilter}
                            horizontalUI={horizontalUI}
                            filterCount={localFilters.length}
                            showNestedArrow={showNestedArrow}
                            {...commonProps}
                        />
                    ))
                )
            ) : null}
            {(!singleFilter || customActions) && (
                <div className="mt" style={{ display: 'flex', alignItems: 'center' }}>
                    {!singleFilter && (
                        <Button
                            type="dashed"
                            onClick={() => addFilter()}
                            data-attr="add-action-event-button"
                            icon={<PlusCircleOutlined />}
                            disabled={disabled}
                            className="add-action-event-button"
                        >
                            {buttonCopy || 'Action or event'}
                        </Button>
                    )}
                    {customActions}
                </div>
            )}
        </div>
    )
}
