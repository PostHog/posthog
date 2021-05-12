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
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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
    showLetters?: boolean // Whether to show a letter indicator identifying each graph
    showOr?: boolean // Whether to show the "OR" label after each filter
    horizontalUI?: boolean
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
    horizontalUI = false,
}: ActionFilterProps): JSX.Element {
    const logic = entityFilterLogic({ setFilters, filters, typeKey })

    const { featureFlags } = useValues(featureFlagLogic)

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
                            horizontalUI={horizontalUI}
                            filterCount={localFilters.length}
                        />
                    ))
                )
            ) : null}
            {!singleFilter && (
                <div className="mt">
                    <Button
                        type={featureFlags[FEATURE_FLAGS.QUERY_UX_V2] ? 'dashed' : 'primary'}
                        onClick={() => addFilter()}
                        style={{ marginTop: '0.5rem' }}
                        data-attr="add-action-event-button"
                        icon={<PlusCircleOutlined />}
                        disabled={disabled}
                        className={`add-action-event-button${featureFlags[FEATURE_FLAGS.QUERY_UX_V2] ? ' new-ui' : ''}`}
                    >
                        {buttonCopy || 'Action or event'}
                    </Button>
                </div>
            )}
        </div>
    )
}
