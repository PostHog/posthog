import './EntityGroupNode.scss'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { BuiltLogic, useActions } from 'kea'

import { IconPlusSmall, IconTrash, IconUndo } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover, TaxonomicPopoverProps } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { uuid } from 'lib/utils'

import { EntityTypes, FilterLogicalOperator } from '~/types'

import { LocalFilter } from '../entityFilterLogic'
import { entityFilterLogicType } from '../entityFilterLogicType'
import { ActionFilterRow, MathAvailability, MathSelector } from './ActionFilterRow'

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
}: EntityGroupNodeProps): JSX.Element {
    const { updateFilter: updateSeriesFilter, removeLocalFilter, splitLocalFilter } = useActions(logic)

    // Ensure nested filters have order set for entityFilterVisible tracking.
    // This is critical after deletion: if we delete event[1] from [0,1,2], we get [0,2] but need [0,1].
    // TODO: Probably handle in the logic
    const values =
        (filter.values as LocalFilter[] | null | undefined)?.map((val, i) => ({
            ...val,
            order: i,
        })) || []

    // Create a wrapped logic that intercepts nested filter updates
    const createNestedLogicWrapper = (eventIndex: number): BuiltLogic<entityFilterLogicType> => {
        return {
            ...logic,
            actions: {
                ...logic.actions,
                updateFilterProperty: (props: any) => {
                    const newValues = [...values]
                    newValues[eventIndex] = {
                        ...newValues[eventIndex],
                        properties: props.properties,
                    }
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        values: newValues,
                        index,
                    } as any)
                },
                updateFilter: (updates: any) => {
                    const newValues = [...values]
                    newValues[eventIndex] = {
                        ...newValues[eventIndex],
                        ...updates,
                    }
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        values: newValues,
                        index,
                    } as any)
                },
                removeLocalFilter: () => {
                    const newValues = values.filter((_, i) => i !== eventIndex)
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        values: newValues,
                        index,
                    } as any)
                },
                splitLocalFilter: () => {
                    // Split is handled at parent level, not needed for nested
                },
            } as any,
        } as any
    }

    const { setNodeRef, attributes, transform, transition, isDragging } = useSortable({ id: filter.uuid })

    const handleOperatorChange = (operator: FilterLogicalOperator): void => {
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator,
            values,
            index,
        } as any)
    }

    const handleMathChange = (filterIndex: number, math: string): void => {
        // Propagate math to all nested values
        const updatedValues = values.map((val) => ({
            ...val,
            math: math || undefined,
        }))
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            values: updatedValues,
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
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            values: [...values, newEvent],
            index,
        } as any)
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
                    {showSeriesIndicator && (
                        <div className="EntityGroupNode__series-indicator">
                            {seriesIndicatorType === 'numeric' ? (
                                <span>{index + 1}</span>
                            ) : (
                                <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
                            )}
                        </div>
                    )}

                    <div className="EntityGroupNode__header-controls">
                        <div className="EntityGroupNode__control-group">
                            <span className="EntityGroupNode__control-label">Operator:</span>
                            <LemonSelect
                                size="small"
                                value={filter.operator || FilterLogicalOperator.Or}
                                options={[
                                    {
                                        label: 'Or',
                                        value: FilterLogicalOperator.Or,
                                    },
                                    {
                                        label: 'And',
                                        value: FilterLogicalOperator.And,
                                    },
                                ]}
                                onChange={handleOperatorChange}
                                disabled={disabled || readOnly}
                                dropdownMatchSelectWidth={false}
                                dropdownPlacement="bottom-start"
                                data-attr={`group-operator-selector-${index}`}
                            />
                        </div>
                        <div className="EntityGroupNode__control-group">
                            <span className="EntityGroupNode__control-label">Math:</span>
                            <MathSelector
                                size="small"
                                math={filter.math}
                                index={index}
                                onMathSelect={handleMathChange}
                                disabled={disabled || readOnly}
                                mathAvailability={MathAvailability.All}
                                trendsDisplayCategory={trendsDisplayCategory}
                            />
                        </div>
                    </div>

                    {!readOnly && (
                        <>
                            <LemonButton
                                size="small"
                                icon={<IconTrash />}
                                onClick={() => removeLocalFilter({ index })}
                                className="EntityGroupNode__delete-btn"
                                data-attr={`group-filter-delete-${index}`}
                            />
                            <LemonButton
                                size="small"
                                icon={<IconUndo />}
                                onClick={() => splitLocalFilter(index)}
                                className="EntityGroupNode__split-btn"
                                data-attr={`group-filter-split-${index}`}
                            />
                        </>
                    )}
                </div>

                {/* Events section - render each value as ActionFilterRow */}
                <ul className="EntityGroupNode__events-section">
                    {values.map((eventFilter, eventIndex) => (
                        <div key={eventFilter.uuid || eventIndex}>
                            <ActionFilterRow
                                logic={createNestedLogicWrapper(eventIndex)}
                                filter={eventFilter}
                                index={eventFilter.order}
                                typeKey={`group-${index}-${eventIndex}`}
                                mathAvailability={MathAvailability.None}
                                hideRename
                                hideDuplicate
                                hideDeleteBtn={values.length <= 1 || readOnly}
                                filterCount={values.length}
                                sortable={false}
                                hasBreakdown={hasBreakdown}
                                disabled={disabled || readOnly}
                                readOnly={readOnly}
                                actionsTaxonomicGroupTypes={actionsTaxonomicGroupTypes}
                                trendsDisplayCategory={trendsDisplayCategory}
                                showNumericalPropsOnly={showNumericalPropsOnly}
                                dataWarehousePopoverFields={dataWarehousePopoverFields}
                                excludedProperties={excludedProperties}
                            />
                            {eventIndex < values.length - 1 && (
                                <div className="EntityGroupNode__operator-separator">
                                    <div className="EntityGroupNode__operator-line EntityGroupNode__operator-line--left" />
                                    <div className="EntityGroupNode__operator-text">
                                        {filter.operator || FilterLogicalOperator.Or}
                                    </div>
                                    <div className="EntityGroupNode__operator-line EntityGroupNode__operator-line--right" />
                                </div>
                            )}
                        </div>
                    ))}
                </ul>

                {/* Add event button with popover */}
                {!readOnly && values.length < 10 && (
                    <div className="EntityGroupNode__add-event-wrapper">
                        <TaxonomicPopover
                            data-attr={`add-group-event-${index}`}
                            groupType={TaxonomicFilterGroupType.Events}
                            value={null}
                            icon={<IconPlusSmall />}
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
        </li>
    )
}
