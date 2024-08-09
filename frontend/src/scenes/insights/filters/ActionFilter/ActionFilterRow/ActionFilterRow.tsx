import './ActionFilterRow.scss'

import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { IconCopy, IconEllipsis, IconFilter, IconPencil, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonBadge,
    LemonCheckbox,
    LemonDivider,
    LemonMenu,
    LemonSelect,
    LemonSelectOption,
    LemonSelectOptions,
} from '@posthog/lemon-ui'
import { BuiltLogic, useActions, useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover, TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getEventNamesForAction } from 'lib/utils'
import { useState } from 'react'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { isAllEventsEntityFilter } from 'scenes/insights/utils'
import {
    apiValueToMathType,
    COUNT_PER_ACTOR_MATH_DEFINITIONS,
    MathCategory,
    mathsLogic,
    mathTypeToApiValues,
    PROPERTY_MATH_DEFINITIONS,
} from 'scenes/trends/mathsLogic'

import { actionsModel } from '~/models/actionsModel'
import { isInsightVizNode, isStickinessQuery } from '~/queries/utils'
import {
    ActionFilter,
    ActionFilter as ActionFilterType,
    BaseMathType,
    ChartDisplayCategory,
    CountPerActorMathType,
    EntityType,
    EntityTypes,
    FunnelExclusionLegacy,
    HogQLMathType,
    PropertyFilterValue,
    PropertyMathType,
} from '~/types'

import { LocalFilter } from '../entityFilterLogic'
import { entityFilterLogicType } from '../entityFilterLogicType'

const DragHandle = (props: DraggableSyntheticListeners | undefined): JSX.Element => (
    <span className="ActionFilterRowDragHandle" key="drag-handle" {...props}>
        <SortableDragIcon />
    </span>
)

export enum MathAvailability {
    All,
    ActorsOnly,
    FunnelsOnly,
    None,
}

const getValue = (
    value: string | number | null | undefined,
    filter: ActionFilter
): string | number | null | undefined => {
    if (isAllEventsEntityFilter(filter)) {
        return 'All events'
    } else if (filter.type === 'actions') {
        return typeof value === 'string' ? parseInt(value) : value || undefined
    }
    return value === null ? null : value || undefined
}

export interface ActionFilterRowProps {
    logic: BuiltLogic<entityFilterLogicType>
    filter: LocalFilter
    index: number
    typeKey: string
    mathAvailability: MathAvailability
    singleFilter?: boolean
    hideFilter?: boolean // Hides the local filter options
    hideRename?: boolean // Hides the rename option
    hideDuplicate?: boolean // Hides the duplicate option
    hideDeleteBtn?: boolean // Choose to hide delete btn. You can use the onClose function passed into customRow{Pre|Suf}fix to render the delete btn anywhere
    propertyFiltersPopover?: boolean
    onRenameClick?: () => void // Used to open rename modal
    showSeriesIndicator?: boolean // Show series badge
    seriesIndicatorType?: 'alpha' | 'numeric' // Series badge shows A, B, C | 1, 2, 3
    filterCount: number
    sortable: boolean
    customRowSuffix?:
        | string
        | JSX.Element
        | ((props: {
              filter: ActionFilterType | FunnelExclusionLegacy
              index: number
              onClose: () => void
          }) => JSX.Element) // Custom suffix element to show in each row
    hasBreakdown: boolean // Whether the current graph has a breakdown filter applied
    showNestedArrow?: boolean // Show nested arrows to the left of property filter buttons
    actionsTaxonomicGroupTypes?: TaxonomicFilterGroupType[] // Which tabs to show for actions selector
    propertiesTaxonomicGroupTypes?: TaxonomicFilterGroupType[] // Which tabs to show for property filters
    disabled?: boolean
    readOnly?: boolean
    renderRow?: ({
        seriesIndicator,
        filter,
        suffix,
        propertyFiltersButton,
        renameRowButton,
        deleteButton,
    }: Record<string, JSX.Element | string | undefined>) => JSX.Element // build your own row given these components
    trendsDisplayCategory: ChartDisplayCategory | null
}

export function ActionFilterRow({
    logic,
    filter,
    index,
    typeKey,
    mathAvailability,
    singleFilter,
    hideFilter,
    hideRename,
    hideDuplicate = false,
    hideDeleteBtn = false,
    propertyFiltersPopover = false,
    onRenameClick = () => {},
    showSeriesIndicator,
    seriesIndicatorType = 'alpha',
    filterCount,
    sortable,
    customRowSuffix,
    hasBreakdown,
    showNestedArrow = false,
    actionsTaxonomicGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    propertiesTaxonomicGroupTypes,
    disabled = false,
    readOnly = false,
    renderRow,
    trendsDisplayCategory,
}: ActionFilterRowProps): JSX.Element {
    const { entityFilterVisible } = useValues(logic)
    const {
        updateFilter,
        selectFilter,
        updateFilterMath,
        removeLocalFilter,
        updateFilterProperty,
        setEntityFilterVisibility,
        duplicateFilter,
    } = useActions(logic)
    const { actions } = useValues(actionsModel)
    const { mathDefinitions } = useValues(mathsLogic)
    const { dataWarehouseTablesMap } = useValues(databaseTableListLogic)

    const [isHogQLDropdownVisible, setIsHogQLDropdownVisible] = useState(false)
    const [isMenuVisible, setIsMenuVisible] = useState(false)

    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({ id: filter.uuid })

    const propertyFiltersVisible = typeof filter.order === 'number' ? entityFilterVisible[filter.order] : false

    let name: string | null | undefined, value: PropertyFilterValue
    const {
        math,
        math_property: mathProperty,
        math_hogql: mathHogQL,
        math_group_type_index: mathGroupTypeIndex,
    } = filter

    const onClose = (): void => {
        removeLocalFilter({ ...filter, index })
    }
    const onMathSelect = (_: unknown, selectedMath?: string): void => {
        const mathProperties = selectedMath
            ? {
                  ...mathTypeToApiValues(selectedMath),
                  math_property:
                      mathDefinitions[selectedMath]?.category === MathCategory.PropertyValue
                          ? mathProperty ?? '$time'
                          : undefined,
                  math_hogql:
                      mathDefinitions[selectedMath]?.category === MathCategory.HogQLExpression
                          ? mathHogQL ?? 'count()'
                          : undefined,
              }
            : {
                  math_property: undefined,
                  math_hogql: undefined,
                  math_group_type_index: undefined,
                  math: undefined,
              }

        updateFilterMath({
            index,
            type: filter.type,
            ...mathProperties,
        })
    }
    const onMathPropertySelect = (_: unknown, property: string): void => {
        updateFilterMath({
            ...filter,
            math_hogql: undefined,
            math_property: property,
            index,
        })
    }

    const onMathHogQLSelect = (_: unknown, hogql: string): void => {
        updateFilterMath({
            ...filter,
            math_property: undefined,
            math_hogql: hogql,
            index,
        })
    }

    if (filter.type === EntityTypes.ACTIONS) {
        const action = actions.find((action) => action.id === filter.id)
        name = action?.name || filter.name
        value = action?.id || filter.id
    } else {
        name = filter.name || String(filter.id)
        value = filter.name || filter.id
    }

    const seriesIndicator =
        seriesIndicatorType === 'numeric' ? (
            <SeriesGlyph style={{ borderColor: 'var(--border)' }}>{index + 1}</SeriesGlyph>
        ) : (
            <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
        )
    const filterElement = (
        <TaxonomicPopover
            data-attr={'trend-element-subject-' + index}
            fullWidth
            groupType={filter.type as TaxonomicFilterGroupType}
            value={getValue(value, filter)}
            filter={filter}
            onChange={(changedValue, taxonomicGroupType, item) => {
                const groupType = taxonomicFilterGroupTypeToEntityType(taxonomicGroupType)
                if (groupType === EntityTypes.DATA_WAREHOUSE) {
                    updateFilter({
                        type: groupType,
                        id: changedValue ? String(changedValue) : null,
                        name: item?.name ?? '',
                        id_field: item?.id_field,
                        timestamp_field: item?.timestamp_field,
                        distinct_id_field: item?.distinct_id_field,
                        table_name: item?.name,
                        index,
                    })
                } else {
                    updateFilter({
                        type: groupType || undefined,
                        id: changedValue ? String(changedValue) : null,
                        name: item?.name ?? '',
                        index,
                    })
                }
            }}
            renderValue={() => (
                <span className="text-overflow max-w-full">
                    <EntityFilterInfo filter={filter} />
                </span>
            )}
            groupTypes={actionsTaxonomicGroupTypes}
            placeholder="All events"
            placeholderClass=""
            disabled={disabled || readOnly}
        />
    )

    const suffix = typeof customRowSuffix === 'function' ? customRowSuffix({ filter, index, onClose }) : customRowSuffix

    const propertyFiltersButton = (
        <IconWithCount key="property-filter" count={filter.properties?.length || 0} showZero={false}>
            <LemonButton
                icon={propertyFiltersVisible ? <IconFilter /> : <IconFilter />} // TODO: Get new IconFilterStriked icon
                title="Show filters"
                data-attr={`show-prop-filter-${index}`}
                noPadding
                onClick={() => {
                    typeof filter.order === 'number'
                        ? setEntityFilterVisibility(filter.order, !propertyFiltersVisible)
                        : undefined
                }}
                disabledReason={filter.id === 'empty' ? 'Please select an event first' : undefined}
            />
        </IconWithCount>
    )

    const enablePopup = mathAvailability === MathAvailability.FunnelsOnly

    const renameRowButton = (
        <LemonButton
            key="rename"
            icon={<IconPencil />}
            title="Rename graph series"
            data-attr={`show-prop-rename-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                setIsMenuVisible(false)
                selectFilter(filter)
                onRenameClick()
            }}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Rename' : undefined}
        </LemonButton>
    )

    const duplicateRowButton = (
        <LemonButton
            key="duplicate"
            icon={<IconCopy />}
            title="Duplicate graph series"
            data-attr={`show-prop-duplicate-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                setIsMenuVisible(false)
                duplicateFilter(filter)
            }}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Duplicate' : undefined}
        </LemonButton>
    )

    const deleteButton = (
        <LemonButton
            key="delete"
            icon={<IconTrash />}
            title="Delete graph series"
            data-attr={`delete-prop-filter-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                setIsMenuVisible(false)
                onClose()
            }}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Delete' : undefined}
        </LemonButton>
    )

    const rowStartElements = [
        sortable && filterCount > 1 ? <DragHandle {...listeners} /> : null,
        showSeriesIndicator && <div key="series-indicator">{seriesIndicator}</div>,
    ].filter(Boolean)

    const rowEndElements = !readOnly
        ? [
              !hideFilter && !enablePopup && propertyFiltersButton,
              !hideRename && renameRowButton,
              !hideDuplicate && !singleFilter && duplicateRowButton,
              !hideDeleteBtn && !singleFilter && deleteButton,
          ].filter(Boolean)
        : []

    return (
        <li
            className="ActionFilterRow"
            ref={setNodeRef}
            {...attributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                position: 'relative',
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div className="ActionFilterRow-content">
                {renderRow ? (
                    renderRow({
                        seriesIndicator,
                        filter: filterElement,
                        suffix,
                        propertyFiltersButton: propertyFiltersButton,
                        renameRowButton,
                        deleteButton,
                    })
                ) : (
                    <>
                        {/* left section fixed */}
                        {rowStartElements.length ? (
                            <div className="ActionFilterRow__start">{rowStartElements}</div>
                        ) : null}
                        {/* central section flexible */}
                        <div className="ActionFilterRow__center">
                            <div className="flex-auto overflow-hidden">{filterElement}</div>
                            {customRowSuffix !== undefined && <>{suffix}</>}
                            {mathAvailability !== MathAvailability.None &&
                                mathAvailability !== MathAvailability.FunnelsOnly && (
                                    <>
                                        <MathSelector
                                            math={math}
                                            mathGroupTypeIndex={mathGroupTypeIndex}
                                            index={index}
                                            onMathSelect={onMathSelect}
                                            disabled={readOnly}
                                            style={{ maxWidth: '100%', width: 'initial' }}
                                            mathAvailability={mathAvailability}
                                            trendsDisplayCategory={trendsDisplayCategory}
                                        />
                                        {mathDefinitions[math || BaseMathType.TotalCount]?.category ===
                                            MathCategory.PropertyValue && (
                                            <div className="flex-auto overflow-hidden">
                                                <TaxonomicStringPopover
                                                    groupType={TaxonomicFilterGroupType.NumericalEventProperties}
                                                    groupTypes={[
                                                        TaxonomicFilterGroupType.DataWarehouseProperties,
                                                        TaxonomicFilterGroupType.NumericalEventProperties,
                                                        TaxonomicFilterGroupType.SessionProperties,
                                                    ]}
                                                    schemaColumns={
                                                        filter.type == TaxonomicFilterGroupType.DataWarehouse &&
                                                        filter.name
                                                            ? Object.values(
                                                                  dataWarehouseTablesMap[filter.name]?.fields ?? []
                                                              )
                                                            : []
                                                    }
                                                    value={mathProperty}
                                                    onChange={(currentValue) =>
                                                        onMathPropertySelect(index, currentValue)
                                                    }
                                                    eventNames={name ? [name] : []}
                                                    data-attr="math-property-select"
                                                    renderValue={(currentValue) => (
                                                        <Tooltip
                                                            title={
                                                                currentValue === '$session_duration' ? (
                                                                    <>
                                                                        Calculate{' '}
                                                                        {mathDefinitions[math ?? ''].name.toLowerCase()}{' '}
                                                                        of the session duration. This is based on the{' '}
                                                                        <code>$session_id</code> property associated
                                                                        with events. The duration is derived from the
                                                                        time difference between the first and last event
                                                                        for each distinct <code>$session_id</code>.
                                                                    </>
                                                                ) : (
                                                                    <>
                                                                        Calculate{' '}
                                                                        {mathDefinitions[math ?? ''].name.toLowerCase()}{' '}
                                                                        from property <code>{currentValue}</code>. Note
                                                                        that only {name} occurences where{' '}
                                                                        <code>{currentValue}</code> is set with a
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
                                            </div>
                                        )}
                                        {mathDefinitions[math || BaseMathType.TotalCount]?.category ===
                                            MathCategory.HogQLExpression && (
                                            <div className="flex-auto overflow-hidden">
                                                <LemonDropdown
                                                    visible={isHogQLDropdownVisible}
                                                    closeOnClickInside={false}
                                                    onClickOutside={() => setIsHogQLDropdownVisible(false)}
                                                    overlay={
                                                        // eslint-disable-next-line react/forbid-dom-props
                                                        <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                                                            <HogQLEditor
                                                                value={mathHogQL}
                                                                onChange={(currentValue) => {
                                                                    onMathHogQLSelect(index, currentValue)
                                                                    setIsHogQLDropdownVisible(false)
                                                                }}
                                                            />
                                                        </div>
                                                    }
                                                >
                                                    <LemonButton
                                                        fullWidth
                                                        type="secondary"
                                                        data-attr={`math-hogql-select-${index}`}
                                                        onClick={() =>
                                                            setIsHogQLDropdownVisible(!isHogQLDropdownVisible)
                                                        }
                                                    >
                                                        <code>{mathHogQL}</code>
                                                    </LemonButton>
                                                </LemonDropdown>
                                            </div>
                                        )}
                                    </>
                                )}
                        </div>
                        {/* right section fixed */}
                        {rowEndElements.length ? (
                            <div className="ActionFilterRow__end">
                                {mathAvailability === MathAvailability.FunnelsOnly ? (
                                    <>
                                        {!hideFilter && propertyFiltersButton}
                                        <div className="relative">
                                            <LemonMenu
                                                visible={isMenuVisible}
                                                closeOnClickInside={false}
                                                onVisibilityChange={setIsMenuVisible}
                                                items={[
                                                    {
                                                        label: () => (
                                                            <>
                                                                <LemonCheckbox
                                                                    className="py-1 px-2 flex-row-reverse [&_svg]:ml-1 [&>label]:gap-2.5"
                                                                    checked={math === BaseMathType.FirstTimeForUser}
                                                                    onChange={(checked) => {
                                                                        onMathSelect(
                                                                            index,
                                                                            checked
                                                                                ? BaseMathType.FirstTimeForUser
                                                                                : undefined
                                                                        )
                                                                    }}
                                                                    data-attr={`math-first-time-for-user-${index}`}
                                                                    label="Count by first time for user"
                                                                    fullWidth
                                                                />
                                                                <LemonDivider />
                                                            </>
                                                        ),
                                                    },
                                                    {
                                                        label: () => renameRowButton,
                                                    },
                                                    {
                                                        label: () => duplicateRowButton,
                                                    },
                                                    {
                                                        label: () => deleteButton,
                                                    },
                                                ]}
                                            >
                                                <LemonButton
                                                    size="medium"
                                                    aria-label="Show more actions"
                                                    data-attr={`more-button-${index}`}
                                                    icon={<IconEllipsis />}
                                                    noPadding
                                                />
                                            </LemonMenu>
                                            <LemonBadge
                                                position="top-right"
                                                size="small"
                                                visible={math === BaseMathType.FirstTimeForUser}
                                            />
                                        </div>
                                    </>
                                ) : (
                                    rowEndElements
                                )}
                            </div>
                        ) : null}
                    </>
                )}
            </div>

            {propertyFiltersVisible && (
                <div className="ActionFilterRow-filters">
                    <PropertyFilters
                        pageKey={`${index}-${value}-${typeKey}-filter`}
                        propertyFilters={filter.properties}
                        onChange={(properties) => updateFilterProperty({ properties, index })}
                        showNestedArrow={showNestedArrow}
                        disablePopover={!propertyFiltersPopover}
                        taxonomicGroupTypes={
                            filter.type == TaxonomicFilterGroupType.DataWarehouse
                                ? [TaxonomicFilterGroupType.DataWarehouseProperties]
                                : propertiesTaxonomicGroupTypes
                        }
                        eventNames={
                            filter.type === TaxonomicFilterGroupType.Events && filter.id
                                ? [String(filter.id)]
                                : filter.type === TaxonomicFilterGroupType.Actions && filter.id
                                ? getEventNamesForAction(parseInt(String(filter.id)), actions)
                                : []
                        }
                        schemaColumns={
                            filter.type == TaxonomicFilterGroupType.DataWarehouse && filter.name
                                ? Object.values(dataWarehouseTablesMap[filter.name]?.fields ?? [])
                                : []
                        }
                    />
                </div>
            )}
        </li>
    )
}

interface MathSelectorProps {
    math?: string
    mathGroupTypeIndex?: number | null
    mathAvailability: MathAvailability
    index: number
    disabled?: boolean
    disabledReason?: string
    onMathSelect: (index: number, value: any) => any
    trendsDisplayCategory: ChartDisplayCategory | null
    style?: React.CSSProperties
}

function isPropertyValueMath(math: string | undefined): math is PropertyMathType {
    return !!math && math in PROPERTY_MATH_DEFINITIONS
}

function isCountPerActorMath(math: string | undefined): math is CountPerActorMathType {
    return !!math && math in COUNT_PER_ACTOR_MATH_DEFINITIONS
}

const TRAILING_MATH_TYPES = new Set<string>([BaseMathType.WeeklyActiveUsers, BaseMathType.MonthlyActiveUsers])

function useMathSelectorOptions({
    math,
    index,
    mathAvailability,
    onMathSelect,
    trendsDisplayCategory,
}: MathSelectorProps): LemonSelectOptions<string> {
    const mountedInsightDataLogic = insightDataLogic.findMounted()
    const query = mountedInsightDataLogic?.values?.query

    const isStickiness = query && isInsightVizNode(query) && isStickinessQuery(query.source)

    const { needsUpgradeForGroups, canStartUsingGroups, staticMathDefinitions, staticActorsOnlyMathDefinitions } =
        useValues(mathsLogic)

    const [propertyMathTypeShown, setPropertyMathTypeShown] = useState<PropertyMathType>(
        isPropertyValueMath(math) ? math : PropertyMathType.Average
    )
    const [countPerActorMathTypeShown, setCountPerActorMathTypeShown] = useState<CountPerActorMathType>(
        isCountPerActorMath(math) ? math : CountPerActorMathType.Average
    )

    const options: LemonSelectOption<string>[] = Object.entries(
        mathAvailability != MathAvailability.ActorsOnly ? staticMathDefinitions : staticActorsOnlyMathDefinitions
    )
        .filter(([key]) => {
            if (isStickiness) {
                // Remove WAU and MAU from stickiness insights
                return !TRAILING_MATH_TYPES.has(key)
            }
            return true
        })
        .map(([key, definition]) => {
            const shouldWarnAboutTrailingMath =
                TRAILING_MATH_TYPES.has(key) && trendsDisplayCategory === ChartDisplayCategory.TotalValue
            return {
                value: key,
                icon: shouldWarnAboutTrailingMath ? <IconWarning /> : undefined,
                label: definition.name,
                tooltip: !shouldWarnAboutTrailingMath ? (
                    definition.description
                ) : (
                    <>
                        <p>{definition.description}</p>
                        <i>
                            In total value insights, it's usually not clear what date range "{definition.name}" refers
                            to. For full clarity, we recommend using "Unique users" here instead.
                        </i>
                    </>
                ),
                'data-attr': `math-${key}-${index}`,
            }
        })

    if (mathAvailability !== MathAvailability.ActorsOnly) {
        options.splice(1, 0, {
            value: countPerActorMathTypeShown,
            label: `Count per user ${COUNT_PER_ACTOR_MATH_DEFINITIONS[countPerActorMathTypeShown].shortName}`,
            labelInMenu: (
                <div className="flex items-center gap-2">
                    <span>Count per user</span>
                    <LemonSelect
                        value={countPerActorMathTypeShown}
                        onSelect={(value) => {
                            setCountPerActorMathTypeShown(value as CountPerActorMathType)
                            onMathSelect(index, value)
                        }}
                        options={Object.entries(COUNT_PER_ACTOR_MATH_DEFINITIONS).map(([key, definition]) => ({
                            value: key,
                            label: definition.shortName,
                            'data-attr': `math-${key}-${index}`,
                        }))}
                        onClick={(e) => e.stopPropagation()}
                        size="small"
                        dropdownMatchSelectWidth={false}
                        optionTooltipPlacement="right"
                    />
                </div>
            ),
            tooltip: 'Statistical analysis of event count per user.',
            'data-attr': `math-node-count-per-actor-${index}`,
        })
        options.push({
            value: propertyMathTypeShown,
            label: `Property value ${PROPERTY_MATH_DEFINITIONS[propertyMathTypeShown].shortName}`,
            labelInMenu: (
                <div className="flex items-center gap-2">
                    <span>Property value</span>
                    <LemonSelect
                        value={propertyMathTypeShown}
                        onSelect={(value) => {
                            setPropertyMathTypeShown(value as PropertyMathType)
                            onMathSelect(index, value)
                        }}
                        options={Object.entries(PROPERTY_MATH_DEFINITIONS).map(([key, definition]) => ({
                            value: key,
                            label: definition.shortName,
                            tooltip: definition.description,
                            'data-attr': `math-${key}-${index}`,
                        }))}
                        onClick={(e) => e.stopPropagation()}
                        size="small"
                        dropdownMatchSelectWidth={false}
                        optionTooltipPlacement="right"
                    />
                </div>
            ),
            tooltip: 'Statistical analysis of property value.',
            'data-attr': `math-node-property-value-${index}`,
        })
    }

    options.push({
        value: HogQLMathType.HogQL,
        label: 'HogQL expression',
        tooltip: 'Aggregate events by custom SQL expression.',
        'data-attr': `math-node-hogql-expression-${index}`,
    })

    return [
        {
            options,
            footer:
                needsUpgradeForGroups || canStartUsingGroups ? (
                    <GroupIntroductionFooter needsUpgrade={needsUpgradeForGroups} />
                ) : undefined,
        },
    ]
}

function MathSelector(props: MathSelectorProps): JSX.Element {
    const options = useMathSelectorOptions(props)
    const { math, mathGroupTypeIndex, index, onMathSelect, disabled, disabledReason } = props

    const mathType = apiValueToMathType(math, mathGroupTypeIndex)

    return (
        <LemonSelect
            value={mathType}
            options={options}
            onChange={(value) => onMathSelect(index, value)}
            data-attr={`math-selector-${index}`}
            disabled={disabled}
            disabledReason={disabledReason}
            optionTooltipPlacement="right"
            dropdownMatchSelectWidth={false}
            dropdownPlacement="bottom-start"
        />
    )
}

const taxonomicFilterGroupTypeToEntityTypeMapping: Partial<Record<TaxonomicFilterGroupType, EntityTypes>> = {
    [TaxonomicFilterGroupType.Events]: EntityTypes.EVENTS,
    [TaxonomicFilterGroupType.Actions]: EntityTypes.ACTIONS,
    [TaxonomicFilterGroupType.DataWarehouse]: EntityTypes.DATA_WAREHOUSE,
}

export function taxonomicFilterGroupTypeToEntityType(
    taxonomicFilterGroupType: TaxonomicFilterGroupType
): EntityType | null {
    return taxonomicFilterGroupTypeToEntityTypeMapping[taxonomicFilterGroupType] || null
}
