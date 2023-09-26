import { BuiltLogic, useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    ActionFilter as ActionFilterType,
    ActionFilter,
    EntityType,
    EntityTypes,
    FunnelExclusion,
    PropertyFilterValue,
    BaseMathType,
    PropertyMathType,
    CountPerActorMathType,
    HogQLMathType,
} from '~/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { getEventNamesForAction } from 'lib/utils'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import './ActionFilterRow.scss'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import {
    apiValueToMathType,
    COUNT_PER_ACTOR_MATH_DEFINITIONS,
    MathCategory,
    mathsLogic,
    mathTypeToApiValues,
    PROPERTY_MATH_DEFINITIONS,
} from 'scenes/trends/mathsLogic'
import { actionsModel } from '~/models/actionsModel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicPopover, TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconCopy, IconDelete, IconEdit, IconFilter, IconWithCount } from 'lib/lemon-ui/icons'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect, LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'
import { useState } from 'react'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { entityFilterLogicType } from '../entityFilterLogicType'
import { isAllEventsEntityFilter } from 'scenes/insights/utils'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { LocalFilter } from '../entityFilterLogic'
import { DraggableSyntheticListeners } from '@dnd-kit/core'

const DragHandle = (props: DraggableSyntheticListeners | undefined): JSX.Element => (
    <span className="ActionFilterRowDragHandle" {...props}>
        <SortableDragIcon />
    </span>
)

export enum MathAvailability {
    All,
    ActorsOnly,
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
    } else {
        return value === null ? null : value || undefined
    }
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
        | ((props: { filter: ActionFilterType | FunnelExclusion; index: number; onClose: () => void }) => JSX.Element) // Custom suffix element to show in each row
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
        orLabel,
    }: Record<string, JSX.Element | string | undefined>) => JSX.Element // build your own row given these components
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

    const [isHogQLDropdownVisible, setIsHogQLDropdownVisible] = useState(false)

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
    const onMathSelect = (_: unknown, selectedMath: string): void => {
        updateFilterMath({
            ...mathTypeToApiValues(selectedMath),
            math_property:
                mathDefinitions[selectedMath]?.category === MathCategory.PropertyValue
                    ? mathProperty ?? '$time'
                    : undefined,
            math_hogql:
                mathDefinitions[selectedMath]?.category === MathCategory.HogQLExpression
                    ? mathHogQL ?? 'count()'
                    : undefined,
            type: filter.type,
            index,
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

    const orLabel = <div className="stateful-badge or width-locked">OR</div>

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
            onChange={(changedValue, taxonomicGroupType, item) => {
                updateFilter({
                    type: taxonomicFilterGroupTypeToEntityType(taxonomicGroupType) || undefined,
                    id: changedValue ? String(changedValue) : null,
                    name: item?.name ?? '',
                    index,
                })
            }}
            renderValue={() => (
                <span className="text-overflow max-w-full">
                    <EntityFilterInfo filter={filter} />
                </span>
            )}
            groupTypes={actionsTaxonomicGroupTypes}
            type="secondary"
            status="stealth"
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
                status="primary-alt"
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

    const renameRowButton = (
        <LemonButton
            key="rename"
            icon={<IconEdit />}
            status="primary-alt"
            title="Rename graph series"
            data-attr={`show-prop-rename-${index}`}
            noPadding
            onClick={() => {
                selectFilter(filter)
                onRenameClick()
            }}
        />
    )

    const duplicateRowButton = (
        <LemonButton
            key="duplicate"
            icon={<IconCopy />}
            status="primary-alt"
            title="Duplicate graph series"
            data-attr={`show-prop-duplicate-${index}`}
            noPadding
            onClick={() => {
                duplicateFilter(filter)
            }}
        />
    )

    const deleteButton = (
        <LemonButton
            key="delete"
            icon={<IconDelete />}
            status="primary-alt"
            title="Delete graph series"
            data-attr={`delete-prop-filter-${index}`}
            noPadding
            onClick={onClose}
        />
    )

    const rowStartElements = [
        sortable && filterCount > 1 ? <DragHandle {...listeners} /> : null,
        showSeriesIndicator && <div key="series-indicator">{seriesIndicator}</div>,
    ].filter(Boolean)

    const rowEndElements = !readOnly
        ? [
              !hideFilter && propertyFiltersButton,
              !hideRename && renameRowButton,
              !hideDuplicate && !singleFilter && duplicateRowButton,
              !hideDeleteBtn && !singleFilter && deleteButton,
          ].filter(Boolean)
        : []

    return (
        <li
            className={'ActionFilterRow'}
            ref={setNodeRef}
            {...attributes}
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
                        orLabel,
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
                            {mathAvailability !== MathAvailability.None && (
                                <>
                                    <MathSelector
                                        math={math}
                                        mathGroupTypeIndex={mathGroupTypeIndex}
                                        index={index}
                                        onMathSelect={onMathSelect}
                                        disabled={readOnly}
                                        style={{ maxWidth: '100%', width: 'initial' }}
                                        mathAvailability={mathAvailability}
                                    />
                                    {mathDefinitions[math || BaseMathType.TotalCount]?.category ===
                                        MathCategory.PropertyValue && (
                                        <div className="flex-auto overflow-hidden">
                                            <TaxonomicStringPopover
                                                groupType={TaxonomicFilterGroupType.NumericalEventProperties}
                                                groupTypes={[
                                                    TaxonomicFilterGroupType.NumericalEventProperties,
                                                    TaxonomicFilterGroupType.Sessions,
                                                ]}
                                                value={mathProperty}
                                                onChange={(currentValue) => onMathPropertySelect(index, currentValue)}
                                                eventNames={name ? [name] : []}
                                                data-attr="math-property-select"
                                                renderValue={(currentValue) => (
                                                    <Tooltip
                                                        title={
                                                            currentValue === '$session_duration' ? (
                                                                <>
                                                                    Calculate{' '}
                                                                    {mathDefinitions[math ?? ''].name.toLowerCase()} of
                                                                    the session duration. This is based on the{' '}
                                                                    <code>$session_id</code> property associated with
                                                                    events. The duration is derived from the time
                                                                    difference between the first and last event for each
                                                                    distinct <code>$session_id</code>.
                                                                </>
                                                            ) : (
                                                                <>
                                                                    Calculate{' '}
                                                                    {mathDefinitions[math ?? ''].name.toLowerCase()}{' '}
                                                                    from property <code>{currentValue}</code>. Note that
                                                                    only {name} occurences where{' '}
                                                                    <code>{currentValue}</code> is set with a numeric
                                                                    value will be taken into account.
                                                                </>
                                                            )
                                                        }
                                                        placement="right"
                                                    >
                                                        <div /* <div> needed for <Tooltip /> to work */>
                                                            <PropertyKeyInfo
                                                                value={currentValue}
                                                                disablePopover={true}
                                                            />
                                                        </div>
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
                                                            disablePersonProperties
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
                                                    status="stealth"
                                                    type="secondary"
                                                    data-attr={`math-hogql-select-${index}`}
                                                    onClick={() => setIsHogQLDropdownVisible(!isHogQLDropdownVisible)}
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
                        {rowEndElements.length ? <div className="ActionFilterRow__end">{rowEndElements}</div> : null}
                    </>
                )}
            </div>

            {propertyFiltersVisible && (
                <div className="ActionFilterRow-filters">
                    <PropertyFilters
                        pageKey={`${index}-${value}-${typeKey}-filter`}
                        propertyFilters={filter.properties}
                        onChange={(properties) => updateFilterProperty({ properties, index })}
                        style={{ margin: 0 }}
                        showNestedArrow={showNestedArrow}
                        disablePopover={!propertyFiltersPopover}
                        taxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                        eventNames={
                            filter.type === TaxonomicFilterGroupType.Events && filter.id
                                ? [String(filter.id)]
                                : filter.type === TaxonomicFilterGroupType.Actions && filter.id
                                ? getEventNamesForAction(parseInt(String(filter.id)), actions)
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
    onMathSelect: (index: number, value: any) => any
    style?: React.CSSProperties
}

function isPropertyValueMath(math: string | undefined): math is PropertyMathType {
    return !!math && math in PROPERTY_MATH_DEFINITIONS
}

function isCountPerActorMath(math: string | undefined): math is CountPerActorMathType {
    return !!math && math in COUNT_PER_ACTOR_MATH_DEFINITIONS
}

function useMathSelectorOptions({
    math,
    index,
    mathAvailability,
    onMathSelect,
}: MathSelectorProps): LemonSelectOptions<string> {
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
    ).map(([key, definition]) => ({
        value: key,
        label: definition.name,
        tooltip: definition.description,
        'data-attr': `math-${key}-${index}`,
    }))

    if (mathAvailability !== MathAvailability.ActorsOnly) {
        options.splice(1, 0, {
            value: countPerActorMathTypeShown,
            label: (
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
            tooltip: 'Statistical analysis of event count per user.',
            'data-attr': `math-node-count-per-actor-${index}`,
        })
        options.push({
            value: propertyMathTypeShown,
            label: (
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
    const { math, mathGroupTypeIndex, index, onMathSelect, disabled } = props

    const mathType = apiValueToMathType(math, mathGroupTypeIndex)

    return (
        <LemonSelect
            value={mathType}
            options={options}
            onChange={(value) => onMathSelect(index, value)}
            data-attr={`math-selector-${index}`}
            disabled={disabled}
            optionTooltipPlacement="right"
            dropdownMatchSelectWidth={false}
            dropdownPlacement="bottom-start"
        />
    )
}

const taxonomicFilterGroupTypeToEntityTypeMapping: Partial<Record<TaxonomicFilterGroupType, EntityTypes>> = {
    [TaxonomicFilterGroupType.Events]: EntityTypes.EVENTS,
    [TaxonomicFilterGroupType.Actions]: EntityTypes.ACTIONS,
}

export function taxonomicFilterGroupTypeToEntityType(
    taxonomicFilterGroupType: TaxonomicFilterGroupType
): EntityType | null {
    return taxonomicFilterGroupTypeToEntityTypeMapping[taxonomicFilterGroupType] || null
}
