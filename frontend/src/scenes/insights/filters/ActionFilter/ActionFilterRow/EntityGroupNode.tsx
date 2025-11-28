import './EntityGroupNode.scss'

import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { BuiltLogic, useActions, useValues } from 'kea'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover, TaxonomicPopoverProps } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { uuid } from 'lib/utils'
import { isAllEventsEntityFilter } from 'scenes/insights/utils'

import { actionsModel } from '~/models/actionsModel'
import { ActionFilter, EntityTypes, FilterLogicalOperator } from '~/types'

import { LocalFilter } from '../entityFilterLogic'
import { entityFilterLogicType } from '../entityFilterLogicType'
import { MathAvailability, MathSelector } from './ActionFilterRow'

const DragHandle = (props: DraggableSyntheticListeners | undefined): JSX.Element => (
    <span className="ActionFilterRowDragHandle" key="drag-handle" {...props}>
        <SortableDragIcon />
    </span>
)

interface EntityGroupNodeProps {
    logic: BuiltLogic<entityFilterLogicType>
    filter: LocalFilter
    index: number
    filterCount: number
    sortable: boolean
    disabled?: boolean
    readOnly?: boolean
    hideDeleteBtn?: boolean
    hasBreakdown: boolean
    showSeriesIndicator?: boolean
    seriesIndicatorType?: 'alpha' | 'numeric'
    actionsTaxonomicGroupTypes?: any[]
    showNumericalPropsOnly?: boolean
    dataWarehousePopoverFields?: any[]
    excludedProperties?: TaxonomicPopoverProps['excludedProperties']
    trendsDisplayCategory?: any
}

export function EntityGroupNode({
    logic,
    filter,
    index,
    filterCount,
    sortable,
    disabled = false,
    readOnly = false,
    hasBreakdown,
    showSeriesIndicator,
    seriesIndicatorType = 'alpha',
    actionsTaxonomicGroupTypes = [],
    showNumericalPropsOnly,
    dataWarehousePopoverFields,
    excludedProperties,
    trendsDisplayCategory,
}: Omit<EntityGroupNodeProps, 'hideDeleteBtn'>): JSX.Element {
    const { updateFilter, removeLocalFilter } = useActions(logic)

    const values = (filter.values as LocalFilter[] | null | undefined) || []

    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({ id: filter.uuid })

    const operatorOptions: LemonSelectOption<FilterLogicalOperator>[] = [
        { value: FilterLogicalOperator.Or, label: 'OR' },
        { value: FilterLogicalOperator.And, label: 'AND' },
    ]

    const handleOperatorChange = (operator: FilterLogicalOperator): void => {
        updateFilter({
            type: EntityTypes.GROUPS,
            operator,
            values,
            index,
        } as any)
    }

    const handleMathChange = (filterIndex: number, math: string): void => {
        updateFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            values,
            math: math || undefined,
            index: filterIndex,
        } as any)
    }

    const handleAddEvent = (changedValue: any, taxonomicGroupType: any, item: any): void => {
        const newEvent: LocalFilter = {
            id: changedValue ? String(changedValue) : null,
            name: item?.name ?? '',
            type: String(taxonomicGroupType) as any,
            order: values.length,
            uuid: uuid(),
        }
        updateFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            values: [...values, newEvent],
            index,
        } as any)
    }

    const handleRemoveEvent = (eventIndex: number): void => {
        const newValues = values.filter((_, i) => i !== eventIndex)
        if (newValues.length === 0) {
            removeLocalFilter({
                ...filter,
                index,
            })
        } else {
            updateFilter({
                type: EntityTypes.GROUPS,
                operator: filter.operator,
                values: newValues,
                index,
            } as any)
        }
    }

    const handleEventChange = (eventIndex: number, changedValue: any, taxonomicGroupType: any, item: any): void => {
        const newValues = [...values]
        const eventTypeStr = String(taxonomicGroupType)
        newValues[eventIndex] = {
            ...newValues[eventIndex],
            type: eventTypeStr as any,
            id: changedValue ? String(changedValue) : null,
            name: item?.name ?? '',
        }
        updateFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            values: newValues,
            index,
        } as any)
    }

    const { actions } = useValues(actionsModel)

    const getValue = (actionFilter: ActionFilter): string | number | null | undefined => {
        if (isAllEventsEntityFilter(actionFilter)) {
            return 'All events'
        } else if (actionFilter.type === 'actions') {
            const action = actions.find((action) => action.id === actionFilter.id)
            return action?.id || filter.id
        }
        return actionFilter.name || actionFilter.id
    }

    return (
        <li
            className="EntityGroupNode relative"
            ref={setNodeRef}
            {...attributes}
            style={{
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div className="EntityGroupNode__wrapper">
                {/* Top row: Series indicator, Operator, Aggregation */}
                <div className="EntityGroupNode__header-row">
                    <div className="EntityGroupNode__header-left">
                        {sortable && filterCount > 1 && <DragHandle {...listeners} />}
                        {showSeriesIndicator && (
                            <div className="EntityGroupNode__series-indicator">
                                {seriesIndicatorType === 'numeric' ? (
                                    <span>{index + 1}</span>
                                ) : (
                                    <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
                                )}
                            </div>
                        )}
                    </div>

                    <div className="EntityGroupNode__header-controls">
                        <LemonSelect
                            value={filter.operator || FilterLogicalOperator.Or}
                            options={operatorOptions}
                            onChange={handleOperatorChange}
                            disabled={disabled || readOnly || values.length < 2}
                            size="small"
                            dropdownMatchSelectWidth={false}
                            data-attr={`group-operator-selector-${index}`}
                        />
                        <MathSelector
                            math={filter.math}
                            index={index}
                            onMathSelect={handleMathChange}
                            disabled={disabled || readOnly}
                            mathAvailability={MathAvailability.All}
                            trendsDisplayCategory={trendsDisplayCategory}
                        />
                    </div>
                </div>

                {/* Events section */}
                <div className="EntityGroupNode__events-section">
                    {values.map((eventFilter, eventIndex) => {
                        return (
                            <div key={eventFilter.uuid || eventIndex} className="EntityGroupNode__event-item">
                                <TaxonomicPopover
                                    data-attr={`group-event-${index}-${eventIndex}`}
                                    fullWidth
                                    groupType={eventFilter.type as TaxonomicFilterGroupType}
                                    value={getValue(filter)}
                                    filter={eventFilter}
                                    onChange={(changedValue, taxonomicGroupType, item) => {
                                        handleEventChange(eventIndex, changedValue, taxonomicGroupType, item)
                                    }}
                                    renderValue={() => (
                                        <span className="EntityGroupNode__event-value">
                                            {eventFilter.id ? (
                                                <EntityFilterInfo filter={eventFilter} />
                                            ) : (
                                                <span className="EntityGroupNode__event-placeholder">Select event</span>
                                            )}
                                        </span>
                                    )}
                                    groupTypes={actionsTaxonomicGroupTypes}
                                    placeholder="Select event"
                                    disabled={disabled || readOnly}
                                    showNumericalPropsOnly={showNumericalPropsOnly}
                                    dataWarehousePopoverFields={dataWarehousePopoverFields}
                                    excludedProperties={excludedProperties}
                                />
                                {!readOnly && values.length > 1 && (
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        noPadding
                                        onClick={() => handleRemoveEvent(eventIndex)}
                                        title="Remove event"
                                        data-attr={`remove-group-event-${index}-${eventIndex}`}
                                        className="EntityGroupNode__event-delete"
                                    />
                                )}
                            </div>
                        )
                    })}

                    {/* Add event button with popover */}
                    {!readOnly && values.length < 10 && (
                        <div className="EntityGroupNode__add-event-wrapper">
                            <TaxonomicPopover
                                data-attr={`add-group-event-${index}`}
                                groupType={TaxonomicFilterGroupType.Events}
                                value={null}
                                icon={<IconPlusSmall />}
                                size="small"
                                onChange={(changedValue, taxonomicGroupType, item) => {
                                    handleAddEvent(changedValue, taxonomicGroupType, item)
                                }}
                                groupTypes={actionsTaxonomicGroupTypes}
                                placeholder="Add event"
                                placeholderClass=""
                                showNumericalPropsOnly={showNumericalPropsOnly}
                                dataWarehousePopoverFields={dataWarehousePopoverFields}
                                excludedProperties={excludedProperties}
                            />
                        </div>
                    )}
                </div>
            </div>
        </li>
    )
}
