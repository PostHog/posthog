import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconEllipsis, IconPencil, IconPlusSmall, IconTrash, IconUndo } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import {
    DefinitionPopoverRenderer,
    TaxonomicFilterGroupType,
    isQuickFilterItem,
    quickFilterToPropertyFilters,
} from 'lib/components/TaxonomicFilter/types'
import {
    TaxonomicPopover,
    TaxonomicPopoverProps,
    TaxonomicStringPopover,
} from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { teamLogic } from 'scenes/teamLogic'
import { MathCategory, mathsLogic } from 'scenes/trends/mathsLogic'

import { BaseMathType, EntityTypes, InsightType } from '~/types'

import {
    ActionFilterRow,
    MathAvailability,
    MathSelector,
    taxonomicFilterGroupTypeToEntityType,
} from '../ActionFilterRow/ActionFilterRow'
import { getDefaultMathHogQLExpression } from '../ActionFilterRow/mathUtils'
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
    mathAvailability?: MathAvailability
    showNumericalPropsOnly?: boolean
    dataWarehousePopoverFields?: any[]
    excludedProperties?: TaxonomicPopoverProps['excludedProperties']
    groupTitle?: string
    trendsDisplayCategory?: any
    insightType?: InsightType
    definitionPopoverRenderer?: DefinitionPopoverRenderer
}

export function ActionFilterGroup({
    filter,
    index,
    typeKey,
    filterCount,
    sortable,
    disabled = false,
    readOnly = false,
    hasBreakdown,
    showSeriesIndicator,
    seriesIndicatorType = 'alpha',
    mathAvailability = MathAvailability.All,
    actionsTaxonomicGroupTypes = [],
    showNumericalPropsOnly,
    dataWarehousePopoverFields,
    excludedProperties,
    groupTitle,
    trendsDisplayCategory,
    insightType,
    definitionPopoverRenderer,
}: ActionFilterGroupProps): JSX.Element {
    const effectiveActionsTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.SuggestedFilters,
        ...actionsTaxonomicGroupTypes,
    ].filter((groupType) => groupType !== TaxonomicFilterGroupType.DataWarehouse)

    const { currentTeamId } = useValues(teamLogic)
    const { removeLocalFilter, splitLocalFilter, showModal, selectFilter } = useActions(entityFilterLogic({ typeKey }))
    const { mathDefinitions } = useValues(mathsLogic)
    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({ id: filter.uuid })

    const groupLogic = actionFilterGroupLogic({ filterUuid: filter.uuid, typeKey, groupIndex: index })
    const { nestedFilters, operator, isHogQLDropdownVisible, groupFilter } = useValues(groupLogic)
    const {
        addNestedFilter,
        updateNestedFilterProperties,
        setMath,
        setMathProperty,
        setMathHogQL,
        setHogQLDropdownVisible,
    } = useActions(groupLogic)
    const defaultMathHogQLExpression = getDefaultMathHogQLExpression(insightType)

    return (
        <li
            className="ActionFilterGroup relative min-w-0 max-w-full list-none"
            ref={setNodeRef}
            {...attributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div
                className={clsx('flex flex-col overflow-hidden min-w-0', {
                    'border border-primary rounded hover:border-secondary': insightType === InsightType.TRENDS,
                })}
            >
                {/* Header: series indicator, math controls, action buttons */}
                <div
                    className={clsx(
                        'ActionFilterGroup--header flex items-center gap-x-2 gap-y-1 px-2 @min-[500px]/editor-panel:px-4 border-b border-primary',
                        insightType === InsightType.FUNNELS ? 'py-4' : 'py-2 @min-[500px]/editor-panel:py-3'
                    )}
                >
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-2 min-w-0">
                        {sortable && filterCount > 1 && (
                            <span className="ActionFilterRowDragHandle" {...listeners}>
                                <SortableDragIcon />
                            </span>
                        )}
                        {showSeriesIndicator && (
                            <div className="shrink-0">
                                {seriesIndicatorType === 'numeric' ? (
                                    <SeriesGlyph style={{ borderColor: 'var(--color-border-primary)' }}>
                                        {index + 1}
                                    </SeriesGlyph>
                                ) : (
                                    <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
                                )}
                            </div>
                        )}

                        {groupTitle && (
                            <span className="font-medium text-secondary whitespace-nowrap">{groupTitle}</span>
                        )}

                        {mathAvailability !== MathAvailability.None &&
                            mathAvailability !== MathAvailability.FunnelsOnly && (
                                // we use flex-wrap when the math name is long so "Math:" and the
                                // select can stack, but flex-nowrap for short names so they stay together.
                                // CSS can't solve this because the select width varies by content.
                                // Remove after insight-editor-panel experiment ends
                                <div
                                    className={clsx(
                                        'flex items-center gap-2',
                                        (mathDefinitions[filter.math || BaseMathType.TotalCount]?.name?.length ?? 0) >
                                            25
                                            ? 'flex-wrap'
                                            : ''
                                    )}
                                >
                                    <span className="font-medium text-secondary whitespace-nowrap">Math:</span>
                                    <MathSelector
                                        size="small"
                                        math={filter.math}
                                        mathGroupTypeIndex={filter.math_group_type_index}
                                        index={index}
                                        onMathSelect={(_, math) => setMath(math, defaultMathHogQLExpression)}
                                        disabled={disabled || readOnly}
                                        mathAvailability={mathAvailability}
                                        trendsDisplayCategory={trendsDisplayCategory}
                                    />
                                    {mathDefinitions[filter.math || BaseMathType.TotalCount]?.category ===
                                        MathCategory.PropertyValue && (
                                        <TaxonomicStringPopover
                                            size="small"
                                            groupType={
                                                filter.math_property_type ||
                                                TaxonomicFilterGroupType.NumericalEventProperties
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
                                                                {mathDefinitions[filter.math ?? '']?.name.toLowerCase()}{' '}
                                                                of the session duration. This is based on the{' '}
                                                                <code>$session_id</code> property associated with
                                                                events. The duration is derived from the time difference
                                                                between the first and last event for each distinct{' '}
                                                                <code>$session_id</code>.
                                                            </>
                                                        ) : (
                                                            <>
                                                                Calculate{' '}
                                                                {mathDefinitions[filter.math ?? '']?.name.toLowerCase()}{' '}
                                                                from property <code>{currentValue}</code>. Note that
                                                                only event occurrences where <code>{currentValue}</code>{' '}
                                                                is set with a numeric value will be taken into account.
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
                                    {mathDefinitions[filter.math || BaseMathType.TotalCount]?.category ===
                                        MathCategory.HogQLExpression && (
                                        <LemonDropdown
                                            visible={isHogQLDropdownVisible}
                                            closeOnClickInside={false}
                                            onClickOutside={() => setHogQLDropdownVisible(false)}
                                            overlay={
                                                // eslint-disable-next-line react/forbid-dom-props
                                                <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                                                    <HogQLEditor
                                                        value={filter.math_hogql || defaultMathHogQLExpression}
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
                                                <code>{filter.math_hogql || defaultMathHogQLExpression}</code>
                                            </LemonButton>
                                        </LemonDropdown>
                                    )}
                                </div>
                            )}
                    </div>

                    {!readOnly && (
                        <div className="flex shrink-0 ml-auto">
                            <LemonMenu
                                placement="bottom-end"
                                items={[
                                    {
                                        items: [
                                            {
                                                label: 'Split events',
                                                size: 'medium',
                                                icon: <IconUndo />,
                                                onClick: () => {
                                                    splitLocalFilter(index)
                                                    posthog.capture('split_events', {
                                                        insight_type: insightType,
                                                        team_id: currentTeamId,
                                                    })
                                                },
                                                'data-attr': `group-filter-split-${index}`,
                                            },
                                        ],
                                    },
                                    {
                                        items: [
                                            {
                                                label: 'Rename',
                                                size: 'medium',
                                                icon: <IconPencil />,
                                                onClick: () => {
                                                    selectFilter(groupFilter ?? null)
                                                    showModal()
                                                },
                                                'data-attr': `group-filter-rename-${index}`,
                                            },
                                            {
                                                label: 'Delete',
                                                size: 'medium',
                                                status: 'danger',
                                                icon: <IconTrash />,
                                                onClick: () => removeLocalFilter({ index }),
                                                'data-attr': `group-filter-delete-${index}`,
                                            },
                                        ],
                                    },
                                ]}
                            >
                                <LemonButton
                                    noPadding
                                    size="medium"
                                    icon={<IconEllipsis />}
                                    aria-label="Show more actions"
                                    data-attr={`group-filter-menu-${index}`}
                                />
                            </LemonMenu>
                        </div>
                    )}
                </div>

                {/* Events list */}
                <ul className="ActionFilterGroup--events-list flex flex-col px-4 py-2.5">
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
                                    actionsTaxonomicGroupTypes={actionsTaxonomicGroupTypes.filter(
                                        (t: TaxonomicFilterGroupType) => t !== TaxonomicFilterGroupType.DataWarehouse
                                    )}
                                    trendsDisplayCategory={trendsDisplayCategory}
                                    showNumericalPropsOnly={showNumericalPropsOnly}
                                    dataWarehousePopoverFields={dataWarehousePopoverFields}
                                    excludedProperties={excludedProperties}
                                    definitionPopoverRenderer={definitionPopoverRenderer}
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
                    <div className="ActionFilterGroup--footer px-4 py-2.5">
                        <TaxonomicPopover
                            data-attr={`add-group-event-${index}`}
                            groupType={TaxonomicFilterGroupType.Events}
                            value={null}
                            icon={<IconPlusSmall />}
                            sideIcon={null}
                            onChange={(value, groupType, item) => {
                                if (isQuickFilterItem(item)) {
                                    if (item.eventName) {
                                        const newIndex = nestedFilters.length
                                        addNestedFilter(item.eventName, item.eventName, EntityTypes.EVENTS)
                                        updateNestedFilterProperties(newIndex, quickFilterToPropertyFilters(item))
                                        posthog.capture('add_event_to_group', {
                                            insight_type: insightType,
                                            team_id: currentTeamId,
                                        })
                                    }
                                    return
                                }
                                const entityType = taxonomicFilterGroupTypeToEntityType(groupType)
                                if (entityType && value) {
                                    addNestedFilter(String(value), item?.name || String(value), entityType)
                                    posthog.capture('add_event_to_group', {
                                        insight_type: insightType,
                                        team_id: currentTeamId,
                                    })
                                }
                            }}
                            groupTypes={effectiveActionsTaxonomicGroupTypes}
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
