import React from 'react'
import { useActions, useValues } from 'kea'
import { Button, Select } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import {
    ActionFilter as ActionFilterType,
    ActionFilter,
    EntityType,
    EntityTypes,
    FunnelStepRangeEntityFilter,
    PropertyFilterValue,
} from '~/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DownOutlined } from '@ant-design/icons'
import { BareEntity, entityFilterLogic } from '../entityFilterLogic'
import { getEventNamesForAction } from 'lib/utils'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import './ActionFilterRow.scss'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { apiValueToMathType, mathsLogic, mathTypeToApiValues } from 'scenes/trends/mathsLogic'
import { GroupsIntroductionOption } from 'lib/introductions/GroupsIntroductionOption'
import { actionsModel } from '~/models/actionsModel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicStringPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import { IconCopy, IconDelete, IconEdit, IconFilter, IconWithCount } from 'lib/components/icons'

import { SortableHandle as sortableHandle } from 'react-sortable-hoc'
import { SortableDragIcon } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'

const DragHandle = sortableHandle(() => (
    <span className="ActionFilterRowDragHandle">
        <SortableDragIcon />
    </span>
))

export enum MathAvailability {
    All,
    ActorsOnly,
    None,
}

export interface ActionFilterRowProps {
    logic: typeof entityFilterLogic
    filter: ActionFilter
    index: number
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
              filter: ActionFilterType | FunnelStepRangeEntityFilter
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
        orLabel,
    }: Record<string, JSX.Element | string | undefined>) => JSX.Element // build your own row given these components
}

export function ActionFilterRow({
    logic,
    filter,
    index,
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
    const { selectedFilter, entities, entityFilterVisible } = useValues(logic)
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

    const propertyFiltersVisible = typeof filter.order === 'number' ? entityFilterVisible[filter.order] : false

    let entity: BareEntity, name: string | null | undefined, value: PropertyFilterValue
    const { math, math_property: mathProperty, math_group_type_index: mathGroupTypeIndex } = filter

    const onClose = (): void => {
        removeLocalFilter({ ...filter, index })
    }
    const onMathSelect = (_: unknown, selectedMath: string): void => {
        updateFilterMath({
            ...mathTypeToApiValues(selectedMath),
            math_property: mathDefinitions[selectedMath]?.onProperty ? mathProperty ?? '$time' : undefined,
            type: filter.type,
            index,
        })
    }
    const onMathPropertySelect = (_: unknown, property: string): void => {
        updateFilterMath({
            ...filter,
            math_property: property,
            index,
        })
    }

    const dropDownCondition = Boolean(
        selectedFilter && selectedFilter?.type === filter.type && selectedFilter?.index === index
    )

    const onClick = (): void => {
        if (dropDownCondition) {
            selectFilter(null)
        } else {
            selectFilter({ ...filter, index })
        }
    }

    if (filter.type === EntityTypes.NEW_ENTITY) {
        name = null
        value = null
    } else {
        entity = (entities[filter.type] as BareEntity[])?.filter((action) => action.id === filter.id)[0] || {}
        name = entity.name || filter.name
        value = entity.id || filter.id
    }

    const orLabel = <div className="stateful-badge or width-locked">OR</div>

    const seriesIndicator =
        seriesIndicatorType === 'numeric' ? (
            <SeriesGlyph style={{ borderColor: 'var(--border)' }}>{index + 1}</SeriesGlyph>
        ) : (
            <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
        )
    const filterElement = (
        <Popup
            overlay={
                <TaxonomicFilter
                    groupType={
                        filter.type === EntityTypes.NEW_ENTITY
                            ? TaxonomicFilterGroupType.Events
                            : (filter.type as TaxonomicFilterGroupType)
                    }
                    value={
                        filter.type === 'actions' && typeof value === 'string' ? parseInt(value) : value || undefined
                    }
                    onChange={(taxonomicGroup, changedValue, item) => {
                        updateFilter({
                            type: taxonomicFilterGroupTypeToEntityType(taxonomicGroup.type) || undefined,
                            id: `${changedValue}`,
                            name: item?.name,
                            index,
                        })
                    }}
                    onClose={() => selectFilter(null)}
                    taxonomicGroupTypes={actionsTaxonomicGroupTypes}
                />
            }
            visible={dropDownCondition}
            onClickOutside={() => selectFilter(null)}
        >
            {({ setRef }) => (
                <Button
                    data-attr={'trend-element-subject-' + index}
                    onClick={onClick}
                    block
                    ref={setRef}
                    disabled={disabled || readOnly}
                    style={{
                        maxWidth: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                    }}
                >
                    <span className="text-overflow" style={{ maxWidth: '100%' }}>
                        <EntityFilterInfo filter={filter} />
                    </span>
                    <DownOutlined style={{ fontSize: 10 }} />
                </Button>
            )}
        </Popup>
    )

    const suffix = typeof customRowSuffix === 'function' ? customRowSuffix({ filter, index, onClose }) : customRowSuffix

    const propertyFiltersButton = (
        <IconWithCount count={filter.properties?.length || 0} showZero={false}>
            <LemonButton
                icon={propertyFiltersVisible ? <IconFilter /> : <IconFilter />} // TODO: Get new IconFilterStriked icon
                type="alt"
                title="Show filters"
                data-attr={`show-prop-filter-${index}`}
                onClick={() => {
                    typeof filter.order === 'number'
                        ? setEntityFilterVisibility(filter.order, !propertyFiltersVisible)
                        : undefined
                }}
            />
        </IconWithCount>
    )

    const renameRowButton = (
        <LemonButton
            icon={<IconEdit />}
            type="alt"
            title="Rename graph series"
            data-attr={`show-prop-rename-${index}`}
            onClick={() => {
                selectFilter(filter)
                onRenameClick()
            }}
        />
    )

    const duplicateRowButton = (
        <LemonButton
            icon={<IconCopy />}
            type="alt"
            title="Duplicate graph series"
            data-attr={`show-prop-duplicate-${index}`}
            onClick={() => {
                duplicateFilter(filter)
            }}
        />
    )

    const deleteButton = (
        <LemonButton
            icon={<IconDelete />}
            type="alt"
            title="Delete graph series"
            data-attr={`delete-prop-filter-${index}`}
            onClick={onClose}
        />
    )

    return (
        <div className={'ActionFilterRow'}>
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
                        <div className="row-start">
                            {sortable && filterCount > 1 ? <DragHandle /> : null}
                            {showSeriesIndicator && <div className="col series-indicator">{seriesIndicator}</div>}
                        </div>
                        {/* central section flexible */}
                        <div className="row-center">
                            <div className="col flex-auto">{filterElement}</div>
                            {customRowSuffix !== undefined && <div className="col">{suffix}</div>}
                            {mathAvailability !== MathAvailability.None && (
                                <>
                                    <div className="col">
                                        <MathSelector
                                            math={math}
                                            mathGroupTypeIndex={mathGroupTypeIndex}
                                            index={index}
                                            onMathSelect={onMathSelect}
                                            style={{ maxWidth: '100%', width: 'initial' }}
                                            mathAvailability={mathAvailability}
                                        />
                                    </div>
                                    {mathDefinitions[math || '']?.onProperty && (
                                        <div className="col">
                                            <TaxonomicStringPopup
                                                groupType={TaxonomicFilterGroupType.NumericalEventProperties}
                                                value={mathProperty}
                                                onChange={(currentValue) => onMathPropertySelect(index, currentValue)}
                                                eventNames={name ? [name] : []}
                                                dataAttr="math-property-select"
                                                renderValue={(currentValue) => (
                                                    <Tooltip
                                                        title={
                                                            <>
                                                                Calculate{' '}
                                                                {mathDefinitions[math ?? ''].name.toLowerCase()} from
                                                                property <code>{currentValue}</code>. Note that only{' '}
                                                                {name} occurences where <code>{currentValue}</code> is
                                                                set with a numeric value will be taken into account.
                                                            </>
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
                                </>
                            )}
                        </div>
                        {/* right section fixed */}
                        <div className="row-end">
                            {!readOnly ? (
                                <>
                                    {!hideFilter && propertyFiltersButton}
                                    {!hideRename && renameRowButton}
                                    {!hideDuplicate && !singleFilter && duplicateRowButton}
                                    {!hideDeleteBtn && !singleFilter && deleteButton}
                                </>
                            ) : null}
                        </div>
                    </>
                )}
            </div>

            {propertyFiltersVisible && (
                <div className={`ActionFilterRow-filters`}>
                    <PropertyFilters
                        pageKey={`${index}-${value}-filter`}
                        propertyFilters={filter.properties}
                        onChange={(properties) => updateFilterProperty({ properties, index })}
                        style={{ margin: 0 }}
                        showNestedArrow={showNestedArrow}
                        disablePopover={!propertyFiltersPopover}
                        taxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                        useLemonButton
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
        </div>
    )
}

interface MathSelectorProps {
    math?: string
    mathGroupTypeIndex?: number | null
    mathAvailability: MathAvailability
    index: number
    onMathSelect: (index: number, value: any) => any
    style?: React.CSSProperties
}

const NUMERICAL_REQUIREMENT_NOTICE =
    'This can only be used on properties that have at least one number type occurence in your events.'

function MathSelector({
    math,
    mathGroupTypeIndex,
    mathAvailability,
    index,
    onMathSelect,
    style,
}: MathSelectorProps): JSX.Element {
    const { mathDefinitions, eventMathEntries, propertyMathEntries } = useValues(mathsLogic)

    let relevantEventMathEntries = eventMathEntries
    if (mathAvailability === MathAvailability.ActorsOnly) {
        relevantEventMathEntries = relevantEventMathEntries.filter(([, definition]) => definition.actor)
    }

    let mathType = apiValueToMathType(math, mathGroupTypeIndex)
    if (mathAvailability === MathAvailability.ActorsOnly && !mathDefinitions[mathType]?.actor) {
        // Backwards compatibility for Stickiness insights that had a non-actor value before (e.g. "Total")
        // Such values are assumed to be user aggregation by the backend
        mathType = 'dau'
    }

    return (
        <Select
            style={{ width: 150, ...style }}
            value={mathType}
            onChange={(value) => onMathSelect(index, value)}
            data-attr={`math-selector-${index}`}
            dropdownMatchSelectWidth={false}
            dropdownStyle={{ maxWidth: 320 }}
            listHeight={280}
        >
            <Select.OptGroup key="event aggregates" label="Event aggregation">
                {relevantEventMathEntries.map(([key, { name, description, onProperty }]) => {
                    return (
                        <Select.Option key={key} value={key} data-attr={`math-${key}-${index}`}>
                            <Tooltip
                                title={
                                    onProperty ? (
                                        <>
                                            {description}
                                            <br />
                                            {NUMERICAL_REQUIREMENT_NOTICE}
                                        </>
                                    ) : (
                                        description
                                    )
                                }
                                placement="right"
                            >
                                <div
                                    style={{
                                        height: '100%',
                                        width: '100%',
                                        paddingRight: 8,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                    }}
                                >
                                    {name}
                                </div>
                            </Tooltip>
                        </Select.Option>
                    )
                })}
                {/* :KLUDGE: Select only allows Select.Option as children, so render groups option directly rather than as a child */}
                {GroupsIntroductionOption({ value: '' })}
            </Select.OptGroup>
            {mathAvailability !== MathAvailability.ActorsOnly && (
                <Select.OptGroup key="property aggregates" label="Property aggregation">
                    {propertyMathEntries.map(([key, { name, description, onProperty }]) => {
                        return (
                            <Select.Option key={key} value={key} data-attr={`math-${key}-${index}`}>
                                <Tooltip
                                    title={
                                        onProperty ? (
                                            <>
                                                {description}
                                                <br />
                                                {NUMERICAL_REQUIREMENT_NOTICE}
                                            </>
                                        ) : (
                                            description
                                        )
                                    }
                                    placement="right"
                                >
                                    <div style={{ height: '100%', width: '100%' }}>{name}</div>
                                </Tooltip>
                            </Select.Option>
                        )
                    })}
                </Select.OptGroup>
            )}
        </Select>
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
