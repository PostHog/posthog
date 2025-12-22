import './ActionFilterGroup.scss'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { BuiltLogic, useActions } from 'kea'
import { useValues } from 'kea'

import { IconPlusSmall, IconTrash, IconUndo } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { defaultDataWarehousePopoverFields } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    TaxonomicPopover,
    TaxonomicPopoverProps,
    TaxonomicStringPopover,
} from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { uuid } from 'lib/utils'
import { MathCategory, mathTypeToApiValues, mathsLogic } from 'scenes/trends/mathsLogic'

import { BaseMathType, EntityTypes, FilterLogicalOperator } from '~/types'

import {
    ActionFilterRow,
    MathAvailability,
    MathSelector,
    taxonomicFilterGroupTypeToEntityType,
} from '../ActionFilterRow/ActionFilterRow'
import { LocalFilter } from '../entityFilterLogic'
import { entityFilterLogicType } from '../entityFilterLogicType'
import { actionFilterGroupLogic } from './actionFilterGroupLogic'

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
    const { setNodeRef, attributes, transform, transition, isDragging } = useSortable({ id: filter.uuid })
    const { isHogQLDropdownVisible } = useValues(actionFilterGroupLogic({ filterUuid: filter.uuid }))
    const { setHogQLDropdownVisible } = useActions(actionFilterGroupLogic({ filterUuid: filter.uuid }))

    // Ensure nested filters have order set for entityFilterVisible tracking.
    // This is critical after deletion: if we delete event[1] from [0,1,2], we get [0,2] but need [0,1].
    const nestedFilters =
        (filter.nestedFilters as LocalFilter[] | null | undefined)?.map((val, i) => ({
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
                    const newNestedFilters = [...nestedFilters]
                    newNestedFilters[eventIndex] = {
                        ...newNestedFilters[eventIndex],
                        properties: props.properties,
                    }
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        nestedFilters: newNestedFilters,
                        index,
                    } as any)
                },
                updateFilter: (updates: any) => {
                    const newNestedFilters = [...nestedFilters]
                    newNestedFilters[eventIndex] = {
                        ...newNestedFilters[eventIndex],
                        ...updates,
                    }
                    const groupName = newNestedFilters.map((v) => v.name).join(', ')
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        nestedFilters: newNestedFilters,
                        name: groupName,
                        index,
                    } as any)
                },
                updateFilterMath: (updates: any) => {
                    const newNestedFilters = [...nestedFilters]
                    newNestedFilters[eventIndex] = {
                        ...newNestedFilters[eventIndex],
                        ...updates,
                    }
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        nestedFilters: newNestedFilters,
                        index,
                    } as any)
                },
                removeLocalFilter: () => {
                    const newNestedFilters = nestedFilters.filter((_, i) => i !== eventIndex)
                    const groupName = newNestedFilters.map((v) => v.name).join(', ')
                    updateSeriesFilter({
                        type: EntityTypes.GROUPS,
                        operator: filter.operator,
                        nestedFilters: newNestedFilters,
                        name: groupName,
                        index,
                    } as any)
                },
            } as any,
        } as any
    }

    const handleMathChange = (filterIndex: number, selectedMath?: string): void => {
        const mathProperty = filter.math_property
        const mathHogQL = filter.math_hogql
        const mathPropertyType = filter.math_property_type

        let mathProperties: any
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

        // Propagate math to all nested filters
        const updatedNestedFilters = nestedFilters.map((val) => ({
            ...val,
            ...mathProperties,
        }))
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            nestedFilters: updatedNestedFilters,
            ...mathProperties,
            index: filterIndex,
        } as any)
    }

    const handleMathPropertySelect = (property: string, groupType: TaxonomicFilterGroupType): void => {
        const mathProperties = {
            math_property: property,
            math_property_type: groupType,
            math_hogql: undefined,
        }
        // Propagate to all nested filters
        const updatedNestedFilters = nestedFilters.map((val) => ({
            ...val,
            ...mathProperties,
        }))
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            nestedFilters: updatedNestedFilters,
            math: filter.math,
            ...mathProperties,
            index,
        } as any)
    }

    const handleMathHogQLSelect = (hogql: string): void => {
        const mathProperties = {
            math_property: undefined,
            math_property_type: undefined,
            math_hogql: hogql,
        }
        // Propagate to all nested filters
        const updatedNestedFilters = nestedFilters.map((val) => ({
            ...val,
            ...mathProperties,
        }))
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            nestedFilters: updatedNestedFilters,
            math: filter.math,
            ...mathProperties,
            index,
        } as any)
    }

    const handleAddEvent = (changedValue: any, taxonomicGroupType: any, item: any): void => {
        const groupType = taxonomicFilterGroupTypeToEntityType(taxonomicGroupType)
        const mathProperties = {
            ...(filter.math && { math: filter.math }),
            ...(filter.math_property && { math_property: filter.math_property }),
            ...(filter.math_property_type && { math_property_type: filter.math_property_type }),
            ...(filter.math_hogql && { math_hogql: filter.math_hogql }),
            ...(filter.math_group_type_index !== undefined && { math_group_type_index: filter.math_group_type_index }),
        }

        const newEvent: LocalFilter = {
            id: changedValue ? String(changedValue) : null,
            name: item?.name ?? '',
            type: groupType ?? (String(taxonomicGroupType) as any),
            order: nestedFilters.length,
            uuid: uuid(),
            ...mathProperties,
            ...(groupType === EntityTypes.DATA_WAREHOUSE && {
                table_name: item?.name,
                ...Object.fromEntries(
                    (dataWarehousePopoverFields ?? defaultDataWarehousePopoverFields).map(({ key }) => [
                        key,
                        item?.[key],
                    ])
                ),
            }),
        }

        const updatedNestedFilters = [...nestedFilters, newEvent]
        const groupName = updatedNestedFilters.map((v) => v.name).join(', ')
        updateSeriesFilter({
            type: EntityTypes.GROUPS,
            operator: filter.operator,
            nestedFilters: updatedNestedFilters,
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
                <div className="ActionFilterGroup__header-row">
                    {/* First row: badge, operator, math controls */}
                    <div className="ActionFilterGroup__configuration">
                        {showSeriesIndicator && (
                            <div className="ActionFilterGroup__series-indicator">
                                {seriesIndicatorType === 'numeric' ? (
                                    <span>{index + 1}</span>
                                ) : (
                                    <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
                                )}
                            </div>
                        )}

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
                            {(mathDefinitions as Record<string, any>)[filter.math || BaseMathType.TotalCount]
                                ?.category === MathCategory.PropertyValue && (
                                <TaxonomicStringPopover
                                    size="small"
                                    groupType={
                                        filter.math_property_type || TaxonomicFilterGroupType.NumericalEventProperties
                                    }
                                    groupTypes={[
                                        TaxonomicFilterGroupType.DataWarehouseProperties,
                                        TaxonomicFilterGroupType.NumericalEventProperties,
                                        TaxonomicFilterGroupType.SessionProperties,
                                        TaxonomicFilterGroupType.PersonProperties,
                                        TaxonomicFilterGroupType.DataWarehousePersonProperties,
                                    ]}
                                    value={filter.math_property}
                                    onChange={(currentValue, groupType) =>
                                        handleMathPropertySelect(currentValue, groupType)
                                    }
                                    eventNames={nestedFilters.map((v) => v.name).filter(Boolean) as string[]}
                                    data-attr="math-property-select"
                                    showNumericalPropsOnly={showNumericalPropsOnly}
                                    renderValue={(currentValue) => (
                                        <Tooltip
                                            title={
                                                currentValue === '$session_duration' ? (
                                                    <>
                                                        Calculate{' '}
                                                        {(mathDefinitions as Record<string, any>)[
                                                            filter.math ?? ''
                                                        ].name.toLowerCase()}{' '}
                                                        of the session duration. This is based on the{' '}
                                                        <code>$session_id</code> property associated with events. The
                                                        duration is derived from the time difference between the first
                                                        and last event for each distinct <code>$session_id</code>.
                                                    </>
                                                ) : (
                                                    <>
                                                        Calculate{' '}
                                                        {(mathDefinitions as Record<string, any>)[
                                                            filter.math ?? ''
                                                        ].name.toLowerCase()}{' '}
                                                        from property <code>{currentValue}</code>. Note that only event
                                                        occurrences where <code>{currentValue}</code> is set with a
                                                        numeric value will be taken into account.
                                                    </>
                                                )
                                            }
                                            placement="right"
                                        >
                                            <PropertyKeyInfo
                                                value={currentValue}
                                                disablePopover
                                                type={TaxonomicFilterGroupType.EventProperties}
                                            />
                                        </Tooltip>
                                    )}
                                />
                            )}
                        </div>

                        {/* SQL selector (only shown when HogQL expression is selected) */}
                        {(mathDefinitions as Record<string, any>)[filter.math || BaseMathType.TotalCount]?.category ===
                            MathCategory.HogQLExpression && (
                            <div className="ActionFilterGroup__hogql_selector">
                                <div className="ActionFilterGroup__control-group">
                                    <LemonDropdown
                                        visible={isHogQLDropdownVisible}
                                        closeOnClickInside={false}
                                        onClickOutside={() => setHogQLDropdownVisible(false)}
                                        overlay={
                                            // eslint-disable-next-line react/forbid-dom-props
                                            <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                                                <HogQLEditor
                                                    value={filter.math_hogql || 'count()'}
                                                    onChange={(currentValue) => {
                                                        handleMathHogQLSelect(currentValue)
                                                        setHogQLDropdownVisible(false)
                                                    }}
                                                />
                                            </div>
                                        }
                                    >
                                        <LemonButton
                                            fullWidth
                                            type="secondary"
                                            size="small"
                                            data-attr={`math-hogql-select-${index}`}
                                            onClick={() => setHogQLDropdownVisible(!isHogQLDropdownVisible)}
                                        >
                                            <code>{filter.math_hogql || 'count()'}</code>
                                        </LemonButton>
                                    </LemonDropdown>
                                </div>
                            </div>
                        )}
                    </div>

                    {!readOnly && (
                        <div className="ActionFilterGroup__configuration_buttons">
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
                        </div>
                    )}
                </div>

                {/* Events section - render each nested filter as ActionFilterRow */}
                <ul className="ActionFilterGroup__events-section">
                    {nestedFilters.map((eventFilter, eventIndex) => (
                        <div key={eventFilter.uuid || eventIndex}>
                            <ActionFilterRow
                                logic={createNestedLogicWrapper(eventIndex)}
                                filter={eventFilter}
                                index={eventFilter.order}
                                typeKey={`group-${index}-${eventIndex}`}
                                mathAvailability={MathAvailability.None}
                                hideRename
                                hideDuplicate
                                hideDeleteBtn={nestedFilters.length <= 1 || readOnly}
                                filterCount={nestedFilters.length}
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
                            {eventIndex < nestedFilters.length - 1 && (
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
                {!readOnly && nestedFilters.length < 10 && (
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
