import React from 'react'
import { useActions, useValues } from 'kea'
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
import { entityFilterLogic } from '../entityFilterLogic'
import { getEventNamesForAction } from 'lib/utils'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import './ActionFilterRow.scss'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { apiValueToMathType, mathsLogic, mathTypeToApiValues } from 'scenes/trends/mathsLogic'
import { actionsModel } from '~/models/actionsModel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicStringPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import { IconCopy, IconDelete, IconEdit, IconFilter, IconWithCount } from 'lib/components/icons'

import { SortableHandle as sortableHandle } from 'react-sortable-hoc'
import { SortableDragIcon } from 'lib/components/icons'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'

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
    const { selectedFilter, entityFilterVisible } = useValues(logic)
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

    let name: string | null | undefined, value: PropertyFilterValue
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
    } else if (filter.type === EntityTypes.ACTIONS) {
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
        <LemonButtonWithPopup
            data-attr={'trend-element-subject-' + index}
            fullWidth
            popup={{
                overlay: (
                    <TaxonomicFilter
                        groupType={
                            filter.type === EntityTypes.NEW_ENTITY
                                ? TaxonomicFilterGroupType.Events
                                : (filter.type as TaxonomicFilterGroupType)
                        }
                        value={
                            filter.type === 'actions' && typeof value === 'string'
                                ? parseInt(value)
                                : value || undefined
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
                ),
                visible: dropDownCondition,
                onClickOutside: () => selectFilter(null),
            }}
            type="secondary"
            status="stealth"
            onClick={onClick}
            disabled={disabled || readOnly}
        >
            <span className="text-overflow" style={{ maxWidth: '100%' }}>
                <EntityFilterInfo filter={filter} />
            </span>
        </LemonButtonWithPopup>
    )

    const suffix = typeof customRowSuffix === 'function' ? customRowSuffix({ filter, index, onClose }) : customRowSuffix

    const propertyFiltersButton = (
        <IconWithCount count={filter.properties?.length || 0} showZero={false}>
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
            />
        </IconWithCount>
    )

    const renameRowButton = (
        <LemonButton
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
            icon={<IconDelete />}
            status="primary-alt"
            title="Delete graph series"
            data-attr={`delete-prop-filter-${index}`}
            noPadding
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
                        <div className="ActionFilterRow__start">
                            {sortable && filterCount > 1 ? <DragHandle /> : null}
                            {showSeriesIndicator && <div>{seriesIndicator}</div>}
                        </div>
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
                                        style={{ maxWidth: '100%', width: 'initial' }}
                                        mathAvailability={mathAvailability}
                                    />
                                    {mathDefinitions[math || '']?.onProperty && (
                                        <div className="flex-auto overflow-hidden">
                                            <TaxonomicStringPopup
                                                groupType={TaxonomicFilterGroupType.NumericalEventProperties}
                                                groupTypes={[
                                                    TaxonomicFilterGroupType.NumericalEventProperties,
                                                    TaxonomicFilterGroupType.Sessions,
                                                ]}
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
                        <div className="ActionFilterRow__end">
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

function MathSelector({
    math,
    mathGroupTypeIndex,
    mathAvailability,
    index,
    onMathSelect,
}: MathSelectorProps): JSX.Element {
    const { mathDefinitions, selectFormattedOptions } = useValues(mathsLogic)

    let relevantEventMathEntries: LemonSelectSection<string>[] = []

    if (mathAvailability === MathAvailability.ActorsOnly) {
        selectFormattedOptions.forEach((section) => {
            const newSection = { ...section }
            newSection.options = section.options.filter(
                (option) => option.value && mathDefinitions[option.value]?.actor
            )
            if (newSection.options.length > 0) {
                relevantEventMathEntries.push(newSection)
            }
        })
    } else {
        relevantEventMathEntries = selectFormattedOptions
    }

    // add data-attr dynamically
    relevantEventMathEntries = relevantEventMathEntries.map((section) => ({
        ...section,
        options: section.options.map((option) => ({ ...option, 'data-attr': `math-${option.value}-${index}` })),
    }))

    let mathType = apiValueToMathType(math, mathGroupTypeIndex)
    if (mathAvailability === MathAvailability.ActorsOnly && !mathDefinitions[mathType]?.actor) {
        // Backwards compatibility for Stickiness insights that had a non-actor value before (e.g. "Total")
        // Such values are assumed to be user aggregation by the backend
        mathType = 'dau'
    }

    return (
        <LemonSelect
            value={mathType}
            options={relevantEventMathEntries}
            onChange={(value) => onMathSelect(index, value)}
            data-attr={`math-selector-${index}`}
            dropdownMatchSelectWidth={false}
            dropdownPlacement={'bottom-start'}
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
