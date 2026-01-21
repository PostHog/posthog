import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'

import { IconPlusSmall, IconTrash, IconUndo } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    TaxonomicPopover,
    TaxonomicPopoverProps,
    TaxonomicStringPopover,
} from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { MathCategory, mathsLogic } from 'scenes/trends/mathsLogic'

import { BaseMathType } from '~/types'

import {
    ActionFilterRow,
    MathAvailability,
    MathSelector,
    taxonomicFilterGroupTypeToEntityType,
} from '../ActionFilterRow/ActionFilterRow'
import { LocalFilter, entityFilterLogic } from '../entityFilterLogic'
import { actionFilterGroupLogic } from './actionFilterGroupLogic'
import { nestedFilterLogic } from './nestedFilterLogic'

interface ActionFilterGroupProps {
    filter: LocalFilter
    index: number
    typeKey: string
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
    filter,
    index,
    typeKey,
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
    const { removeLocalFilter, splitLocalFilter } = useActions(entityFilterLogic({ typeKey }))
    const { mathDefinitions } = useValues(mathsLogic)
    const { setNodeRef, attributes, transform, transition, isDragging } = useSortable({ id: filter.uuid })

    const groupLogic = actionFilterGroupLogic({ filterUuid: filter.uuid, typeKey, groupIndex: index })
    const { nestedFilters, operator, isHogQLDropdownVisible } = useValues(groupLogic)
    const { addNestedFilter, setMath, setMathProperty, setMathHogQL, setHogQLDropdownVisible } = useActions(groupLogic)

    return (
        <li
            className="relative min-w-0 max-w-full list-none"
            ref={setNodeRef}
            {...attributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div className="flex flex-col overflow-hidden border border-primary rounded hover:border-secondary">
                {/* Header: series indicator, math controls, action buttons */}
                <div className="flex flex-wrap items-start justify-between gap-2 px-4 py-3 border-b border-primary">
                    <div className="flex flex-wrap items-center gap-2 min-w-0">
                        {showSeriesIndicator && (
                            <div className="shrink-0">
                                {seriesIndicatorType === 'numeric' ? (
                                    <span>{index + 1}</span>
                                ) : (
                                    <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
                                )}
                            </div>
                        )}

                        <div className="flex flex-wrap items-center gap-2 min-w-0">
                            <span className="font-medium text-secondary whitespace-nowrap">Math:</span>
                            <MathSelector
                                size="small"
                                math={filter.math}
                                mathGroupTypeIndex={filter.math_group_type_index}
                                index={index}
                                onMathSelect={(_, math) => setMath(math)}
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
                                    onChange={setMathProperty}
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

                            {/* HogQL expression selector */}
                            {(mathDefinitions as Record<string, any>)[filter.math || BaseMathType.TotalCount]
                                ?.category === MathCategory.HogQLExpression && (
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
                                                    setMathHogQL(currentValue)
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
                            )}
                        </div>
                    </div>

                    {!readOnly && (
                        <div className="flex shrink-0 gap-1">
                            <Tooltip title="Remove group">
                                <LemonButton
                                    size="small"
                                    icon={<IconTrash />}
                                    onClick={() => removeLocalFilter({ index })}
                                    data-attr={`group-filter-delete-${index}`}
                                />
                            </Tooltip>
                            <Tooltip title="Split events">
                                <LemonButton
                                    size="small"
                                    icon={<IconUndo />}
                                    onClick={() => splitLocalFilter(index)}
                                    data-attr={`group-filter-split-${index}`}
                                />
                            </Tooltip>
                        </div>
                    )}
                </div>

                {/* Events list */}
                <ul className="flex flex-col px-4 py-2.5">
                    {nestedFilters.map((eventFilter, eventIndex) => {
                        const nestedLogicInstance = nestedFilterLogic({
                            groupFilterUuid: filter.uuid,
                            nestedIndex: eventIndex,
                            typeKey,
                            groupIndex: index,
                        })

                        return (
                            <div key={eventFilter.uuid || eventIndex}>
                                <ActionFilterRow
                                    logic={nestedLogicInstance as any}
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
                                    <div className="flex items-center gap-3 mx-0.5 my-2.5">
                                        <div className="flex-1 h-px bg-border-primary" />
                                        <span className="text-[11px] font-semibold text-tertiary uppercase tracking-wide">
                                            {operator}
                                        </span>
                                        <div className="flex-1 h-px bg-border-primary" />
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </ul>

                {/* Add event button */}
                {!readOnly && nestedFilters.length < 10 && (
                    <div className="px-4 py-2.5">
                        <TaxonomicPopover
                            data-attr={`add-group-event-${index}`}
                            groupType={TaxonomicFilterGroupType.Events}
                            value={null}
                            icon={<IconPlusSmall />}
                            sideIcon={null}
                            onChange={(value, groupType, item) => {
                                const entityType = taxonomicFilterGroupTypeToEntityType(groupType)
                                if (entityType && value) {
                                    addNestedFilter(String(value), item?.name || String(value), entityType)
                                }
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
