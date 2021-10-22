import './ActionFilter.scss'
import React, { useEffect } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { entityFilterLogic, toFilters, LocalFilter } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow/ActionFilterRow'
import { Button } from 'antd'
import { PlusCircleOutlined } from '@ant-design/icons'
import { ActionFilter as ActionFilterType, FilterType, FunnelStepRangeEntityFilter, Optional } from '~/types'
import { SortableContainer, SortableActionFilterRow } from './Sortable'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { RenameModal } from 'scenes/insights/ActionFilter/RenameModal'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../../teamLogic'

export interface ActionFilterProps {
    setFilters: (filters: FilterType) => void
    filters: Optional<FilterType, 'type'>
    typeKey: string
    addFilterDefaultOptions?: Record<string, any>
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
    hideRename?: boolean // Hides the rename option
    customRowPrefix?:
        | string
        | JSX.Element
        | ((props: {
              filter: ActionFilterType | FunnelStepRangeEntityFilter
              index: number
              onClose: () => void
          }) => JSX.Element) // Custom prefix element to show in each ActionFilterRow
    customRowSuffix?:
        | string
        | JSX.Element
        | ((props: {
              filter: ActionFilterType | FunnelStepRangeEntityFilter
              index: number
              onClose: () => void
          }) => JSX.Element) // Custom suffix element to show in each ActionFilterRow
    rowClassName?: string
    propertyFilterWrapperClassName?: string
    stripeActionRow?: boolean
    customActions?: JSX.Element // Custom actions to be added next to the add series button
    horizontalUI?: boolean
    fullWidth?: boolean
    showNestedArrow?: boolean // show nested arrows to the left of property filter buttons
    groupTypes?: TaxonomicFilterGroupType[]
    hideDeleteBtn?: boolean
    renderRow?: ({
        seriesIndicator,
        prefix,
        filter,
        suffix,
        propertyFiltersButton,
        deleteButton,
        orLabel,
    }: Record<string, JSX.Element | string | undefined>) => JSX.Element
}

export const ActionFilter = React.forwardRef<HTMLDivElement, ActionFilterProps>(
    (
        {
            setFilters,
            filters,
            typeKey,
            addFilterDefaultOptions = {},
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
            hideRename = false,
            horizontalUI = false,
            fullWidth = false,
            customRowPrefix,
            customRowSuffix,
            rowClassName,
            propertyFilterWrapperClassName,
            stripeActionRow = true,
            customActions,
            showNestedArrow = false,
            groupTypes,
            hideDeleteBtn,
            renderRow,
        },
        ref
    ): JSX.Element => {
        const { currentTeamId } = useValues(teamLogic)
        const logic = entityFilterLogic({
            teamId: currentTeamId,
            setFilters,
            filters,
            typeKey,
            addFilterDefaultOptions,
        })
        const { reportFunnelStepReordered } = useActions(eventUsageLogic)

        const { localFilters } = useValues(logic)
        const { addFilter, setLocalFilters, showModal } = useActions(logic)

        // No way around this. Somehow the ordering of the logic calling each other causes stale "localFilters"
        // to be shown on the /funnels page, even if we try to use a selector with props to hydrate it
        useEffect(
            () => {
                setLocalFilters(filters)
            },
            // eslint-disable-next-line react-hooks/exhaustive-deps
            [filters]
        )

        function onSortEnd({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void {
            function move(arr: LocalFilter[], from: number, to: number): LocalFilter[] {
                const clone = [...arr]
                Array.prototype.splice.call(clone, to, 0, Array.prototype.splice.call(clone, from, 1)[0])
                return clone.map((child, order) => ({ ...child, order }))
            }
            setFilters(toFilters(move(localFilters, oldIndex, newIndex)))
            if (oldIndex !== newIndex) {
                reportFunnelStepReordered()
            }
        }

        const commonProps = {
            logic: logic as any,
            showSeriesIndicator,
            seriesIndicatorType,
            hideMathSelector,
            hidePropertySelector,
            customRowPrefix,
            customRowSuffix,
            rowClassName,
            propertyFilterWrapperClassName,
            stripeActionRow,
            hasBreakdown: !!filters.breakdown,
            fullWidth,
            groupTypes,
            hideDeleteBtn,
            disabled,
            renderRow,
            hideRename,
            onRenameClick: showModal,
        }

        return (
            <div ref={ref}>
                {!hideRename && (
                    <BindLogic
                        logic={entityFilterLogic}
                        props={{ setFilters, filters, typeKey, addFilterDefaultOptions }}
                    >
                        <RenameModal view={filters.insight} typeKey={typeKey} />
                    </BindLogic>
                )}
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
)
