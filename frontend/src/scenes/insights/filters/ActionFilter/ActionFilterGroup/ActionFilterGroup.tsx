import './ActionFilterGroup.scss'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { BuiltLogic, useActions } from 'kea'
import { useValues } from 'kea'

import { IconPlusSmall, IconTrash, IconUndo } from '@posthog/icons'
import { LemonButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover, TaxonomicPopoverProps } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { uuid } from 'lib/utils'
import { MathCategory, mathTypeToApiValues, mathsLogic } from 'scenes/trends/mathsLogic'

import { EntityTypes, FilterLogicalOperator } from '~/types'

import { ActionFilterRow, MathAvailability, MathSelector } from '../ActionFilterRow/ActionFilterRow'
import { LocalFilter } from '../entityFilterLogic'
import { entityFilterLogicType } from '../entityFilterLogicType'

interface ActionFilterGroupProps {
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

export function ActionFilterGroup({
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
}: ActionFilterGroupProps): JSX.Element {
    const { updateFilter: updateSeriesFilter, removeLocalFilter, splitLocalFilter } = useActions(logic)
    const { mathDefinitions } = useValues(mathsLogic)

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
                    const groupName = newValues.map((v) => v.name).join(', ')
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        values: newValues,
                        name: groupName,
                        index,
                    } as any)
                },
                updateFilterMath: (updates: any) => {
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
                    const groupName = newValues.map((v) => v.name).join(', ')
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        values: newValues,
                        name: groupName,
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

    const handleMathChange = (filterIndex: number, selectedMath?: string): void => {
        let mathProperties
        const mathProperty = filter.math_property
        const mathHogQL = filter.math_hogql
        const mathPropertyType = filter.math_property_type

        if (selectedMath) {
            const selectedMathDef = (mathDefinitions as Record<string, any>)[selectedMath]
            const math_property =
                selectedMathDef?.category === MathCategory.PropertyValue ? (mathProperty ?? '$time') : undefined
            const math_hogql =
                selectedMathDef?.category === MathCategory.HogQLExpression ? (mathHogQL ?? 'count()') : undefined
            const apiValues = mathTypeToApiValues(selectedMath)
            mathProperties = {
                ...apiValues,
                ...(apiValues.math_group_type_index === undefined && { math_group_type_index: undefined }),
                math_property,
                math_hogql,
                math_property_type: mathPropertyType,
            }
        } else {
            mathProperties = {
                math_property: undefined,
                math_property_type: undefined,
                math_hogql: undefined,
                math_group_type_index: undefined,
                math: undefined,
            }
        }

        // Propagate math to all nested values
        const updatedValues = values.map((val) => ({
            ...val,
            ...mathProperties,
        }))
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            values: updatedValues,
            ...mathProperties,
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
            ...(filter.math && { math: filter.math }),
            ...(filter.math_property && { math_property: filter.math_property }),
            ...(filter.math_property_type && { math_property_type: filter.math_property_type }),
            ...(filter.math_hogql && { math_hogql: filter.math_hogql }),
            ...(filter.math_group_type_index !== undefined && { math_group_type_index: filter.math_group_type_index }),
        }
        const updatedValues = [...values, newEvent]
        const groupName = updatedValues.map((v) => v.name).join(', ')
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            values: updatedValues,
            name: groupName,
            index,
        } as any)
    }

    return (
        <li
            className="ActionFilterGroup relative"
            ref={setNodeRef}
            {...attributes}
            style={{
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div className="ActionFilterGroup__wrapper">
                {/* Top row: Series indicator, Operator, Aggregation */}
                <div className="ActionFilterGroup__header-row">
                    {showSeriesIndicator && (
                        <div className="ActionFilterGroup__series-indicator">
                            {seriesIndicatorType === 'numeric' ? (
                                <span>{index + 1}</span>
                            ) : (
                                <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
                            )}
                        </div>
                    )}

                    <div className="ActionFilterGroup__header-controls">
                        <div className="ActionFilterGroup__control-group">
                            <span className="ActionFilterGroup__control-label">Operator:</span>
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
                        <div className="ActionFilterGroup__control-group">
                            <span className="ActionFilterGroup__control-label">Math:</span>
                            <MathSelector
                                size="small"
                                math={filter.math}
                                mathGroupTypeIndex={filter.math_group_type_index}
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
                            <Tooltip title="Remove group">
                                <LemonButton
                                    size="small"
                                    icon={<IconTrash />}
                                    onClick={() => removeLocalFilter({ index })}
                                    className="ActionFilterGroup__delete-btn"
                                    data-attr={`group-filter-delete-${index}`}
                                />
                            </Tooltip>
                            <Tooltip title="Split events">
                                <LemonButton
                                    size="small"
                                    icon={<IconUndo />}
                                    onClick={() => splitLocalFilter(index)}
                                    className="ActionFilterGroup__split-btn"
                                    data-attr={`group-filter-split-${index}`}
                                />
                            </Tooltip>
                        </>
                    )}
                </div>

                {/* Events section - render each value as ActionFilterRow */}
                <ul className="ActionFilterGroup__events-section">
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
                                <div className="ActionFilterGroup__operator-separator">
                                    <div className="ActionFilterGroup__operator-line ActionFilterGroup__operator-line--left" />
                                    <div className="ActionFilterGroup__operator-text">
                                        {filter.operator || FilterLogicalOperator.Or}
                                    </div>
                                    <div className="ActionFilterGroup__operator-line ActionFilterGroup__operator-line--right" />
                                </div>
                            )}
                        </div>
                    ))}
                </ul>

                {/* Add event button with popover */}
                {!readOnly && values.length < 10 && (
                    <div className="ActionFilterGroup__add-event-wrapper">
                        <TaxonomicPopover
                            data-attr={`add-group-event-${index}`}
                            groupType={TaxonomicFilterGroupType.Events}
                            value={null}
                            icon={<IconPlusSmall />}
                            sideIcon={null}
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
