import './ActionFilterRow.scss'

import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback } from 'react'

import { IconCopy, IconFilter, IconGroupIntersect, IconPencil, IconTrash } from '@posthog/icons'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import { defaultDataWarehousePopoverFields } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    DataWarehousePopoverField,
    TaxonomicFilterGroupType,
    isQuickFilterItem,
    quickFilterToPropertyFilters,
} from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover, TaxonomicPopoverProps } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconWithCount, SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { getEventNamesForAction } from 'lib/utils'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { MathCategory, mathTypeToApiValues, mathsLogic } from 'scenes/trends/mathsLogic'

import { actionsModel } from '~/models/actionsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    EntityTypes,
    InsightShortId,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
} from '~/types'

import { ActionFilterRowMenu } from './ActionFilterRowMenu'
import { getValue, taxonomicFilterGroupTypeToEntityType } from './actionFilterRowUtils'
import { HogQLMathEditorDropdown } from './HogQLMathEditor'
import { MathSelector } from './MathSelector'
import { BoxPlotPropertySelector, PropertyValueMathSelector } from './PropertyMathSelector'
import type { ActionFilterRowProps } from './types'
import { MathAvailability } from './types'

// Re-export for backward compatibility — these are imported from this file by 28+ consumers
export { MathAvailability } from './types'
export type { ActionFilterRowProps, MathSelectorProps } from './types'
export { taxonomicFilterGroupTypeToEntityType } from './actionFilterRowUtils'
export { MathSelector } from './MathSelector'

interface DragHandleProps {
    listeners: DraggableSyntheticListeners | undefined
}

const DragHandle = ({ listeners }: DragHandleProps): JSX.Element => (
    <span className="ActionFilterRowDragHandle" {...listeners}>
        <SortableDragIcon />
    </span>
)

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
    showCombine = false,
    insightType,
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
    showNumericalPropsOnly,
    allowedMathTypes,
    dataWarehousePopoverFields = defaultDataWarehousePopoverFields,
    filtersLeftPadding = false,
    addFilterDocLink,
    excludedProperties,
    allowNonCapturedEvents,
    hogQLGlobals,
    inlineEventsDocLink,
    definitionPopoverRenderer,
    operatorAllowlist,
}: ActionFilterRowProps & Pick<TaxonomicPopoverProps, 'excludedProperties' | 'allowNonCapturedEvents'>): JSX.Element {
    const effectiveActionsTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.SuggestedFilters,
        ...actionsTaxonomicGroupTypes,
    ]

    const { currentTeamId } = useValues(teamLogic)
    const { entityFilterVisible } = useValues(logic)
    const {
        updateFilter,
        selectFilter,
        updateFilterOptional,
        updateFilterMath,
        removeLocalFilter,
        updateFilterProperty,
        setEntityFilterVisibility,
        duplicateFilter,
        convertFilterToGroup,
    } = useActions(logic)
    const { actions } = useValues(actionsModel)
    const { mathDefinitions } = useValues(mathsLogic)
    const { dataWarehouseTablesMap } = useValues(databaseTableListLogic)

    const mountedInsightDataLogic = insightDataLogic.findMounted({ dashboardItemId: typeKey })
    const query = mountedInsightDataLogic?.values?.query

    const isFunnelContext = mathAvailability === MathAvailability.FunnelsOnly
    const isTrendsContext = trendsDisplayCategory != null

    // Always call hooks for React compliance - provide safe defaults for non-funnel contexts
    // dashboardItemId should be the insight's id, but the typeKey might contain a /on-dashboard- suffix
    const dashboardItemId = typeKey.split('/')[0] as InsightShortId
    const { insightProps: funnelInsightProps } = useValues(
        insightLogic({ dashboardItemId: isFunnelContext ? dashboardItemId : 'new' })
    )
    const { isStepOptional: funnelIsStepOptional } = useValues(funnelDataLogic(funnelInsightProps))

    // Only use the funnel results when in funnel context
    const isStepOptional = isFunnelContext ? funnelIsStepOptional : () => false

    // DWH events are not supported in inline events yet
    const canCombine = showCombine && !singleFilter && filter.type !== EntityTypes.DATA_WAREHOUSE

    const {
        setNodeRef,
        attributes: { 'aria-disabled': _, ...attributes },
        transform,
        transition,
        listeners,
        isDragging,
    } = useSortable({ id: filter.uuid })

    const propertyFiltersVisible = typeof filter.order === 'number' ? entityFilterVisible[filter.order] : false

    let name: string | null | undefined, value: PropertyFilterValue
    const {
        math,
        math_property: mathProperty,
        math_property_type: mathPropertyType,
        math_hogql: mathHogQL,
        math_group_type_index: mathGroupTypeIndex,
    } = filter

    const onClose = (): void => {
        removeLocalFilter({ ...filter, index })
    }

    const onPropertyChange = useCallback(
        (properties: AnyPropertyFilter[]) => updateFilterProperty({ properties, index }),
        [updateFilterProperty, index]
    )

    const onMathSelect = (_: unknown, selectedMath?: string): void => {
        let mathProperties
        if (selectedMath) {
            const math_property =
                mathDefinitions[selectedMath]?.category === MathCategory.PropertyValue
                    ? (mathProperty ?? '$time')
                    : undefined
            const math_hogql =
                mathDefinitions[selectedMath]?.category === MathCategory.HogQLExpression
                    ? (mathHogQL ?? 'count()')
                    : undefined
            mathProperties = {
                ...mathTypeToApiValues(selectedMath),
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

        updateFilterMath({
            index,
            type: filter.type,
            ...mathProperties,
        })
    }

    const onMathPropertySelect = (_: unknown, property: string, groupType: TaxonomicFilterGroupType): void => {
        updateFilterMath({
            ...filter,
            math_hogql: undefined,
            math_property: property,
            math_property_type: groupType,
            index,
        })
    }

    const onMathHogQLSelect = (_: unknown, hogql: string): void => {
        updateFilterMath({
            ...filter,
            math_property: undefined,
            math_property_type: undefined,
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
            <SeriesGlyph style={{ borderColor: 'var(--color-border-primary)' }}>{index + 1}</SeriesGlyph>
        ) : (
            <SeriesLetter seriesIndex={index} hasBreakdown={hasBreakdown} />
        )
    const filterElement = (
        <TaxonomicPopover
            data-attr={'trend-element-subject-' + index}
            fullWidth
            truncate
            groupType={TaxonomicFilterGroupType.SuggestedFilters}
            value={getValue(value, filter)}
            filter={filter}
            onChange={(changedValue, taxonomicGroupType, item) => {
                if (isQuickFilterItem(item)) {
                    if (item.eventName) {
                        updateFilter({
                            type: EntityTypes.EVENTS,
                            id: item.eventName,
                            name: item.eventName,
                            index,
                        })
                    }
                    updateFilterProperty({
                        index,
                        properties: quickFilterToPropertyFilters(item),
                    })
                    return
                }
                if (taxonomicGroupType === TaxonomicFilterGroupType.PageviewEvents) {
                    updateFilter({
                        type: EntityTypes.EVENTS,
                        id: '$pageview',
                        name: '$pageview',
                        index,
                    })
                    updateFilterProperty({
                        index,
                        properties: [
                            {
                                key: '$current_url',
                                value: changedValue ? String(changedValue) : '',
                                operator: PropertyOperator.IContains,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    })
                    return
                }
                if (taxonomicGroupType === TaxonomicFilterGroupType.ScreenEvents) {
                    updateFilter({
                        type: EntityTypes.EVENTS,
                        id: '$screen',
                        name: '$screen',
                        index,
                    })
                    updateFilterProperty({
                        index,
                        properties: [
                            {
                                key: '$screen_name',
                                value: changedValue ? String(changedValue) : '',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    })
                    return
                }
                if (taxonomicGroupType === TaxonomicFilterGroupType.AutocaptureEvents) {
                    updateFilter({
                        type: EntityTypes.EVENTS,
                        id: '$autocapture',
                        name: '$autocapture',
                        index,
                    })
                    updateFilterProperty({
                        index,
                        properties: [
                            {
                                key: '$el_text',
                                value: changedValue ? String(changedValue) : '',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    })
                    return
                }
                const groupType = taxonomicFilterGroupTypeToEntityType(taxonomicGroupType)
                if (groupType === EntityTypes.DATA_WAREHOUSE) {
                    const extraValues = Object.fromEntries(
                        dataWarehousePopoverFields.map(({ key }) => [key, item?.[key]])
                    )
                    updateFilter({
                        type: groupType,
                        id: changedValue ? String(changedValue) : null,
                        name: item?.name ?? '',
                        table_name: item?.name,
                        index,
                        ...extraValues,
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
                    <EntityFilterInfo filter={filter} showIcon />
                </span>
            )}
            groupTypes={effectiveActionsTaxonomicGroupTypes}
            placeholder="All events"
            placeholderClass=""
            disabled={disabled || readOnly}
            showNumericalPropsOnly={showNumericalPropsOnly}
            dataWarehousePopoverFields={
                typeKey === 'plugin-filters' ? ([] as DataWarehousePopoverField[]) : dataWarehousePopoverFields
            }
            excludedProperties={excludedProperties}
            allowNonCapturedEvents={allowNonCapturedEvents}
            definitionPopoverRenderer={definitionPopoverRenderer}
        />
    )

    const suffix = typeof customRowSuffix === 'function' ? customRowSuffix({ filter, index, onClose }) : customRowSuffix

    const propertyFiltersButton = (
        <IconWithCount key="property-filter" count={filter.properties?.length || 0} showZero={false}>
            <LemonButton
                icon={<IconFilter />}
                title="Show filters"
                data-attr={`show-prop-filter-${index}`}
                noPadding
                active={propertyFiltersVisible}
                onClick={() => {
                    typeof filter.order === 'number'
                        ? setEntityFilterVisibility(filter.order, !propertyFiltersVisible)
                        : undefined
                }}
                disabledReason={filter.id === 'empty' ? 'Please select an event first' : undefined}
                tooltip="Show filters"
                tooltipDocLink={addFilterDocLink}
            />
        </IconWithCount>
    )

    // Enable popup menu for funnels and trends contexts where we want to show rename/duplicate/delete/etc in a menu
    const enablePopup = mathAvailability === MathAvailability.FunnelsOnly || isTrendsContext

    const renameRowButton = (
        <LemonButton
            key="rename"
            icon={<IconPencil />}
            title="Rename graph series"
            data-attr={`show-prop-rename-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
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
                duplicateFilter(filter)
            }}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Duplicate' : undefined}
        </LemonButton>
    )

    const combineInlineButton = (
        <LemonButton
            key="combine-inline"
            icon={<IconGroupIntersect />}
            title="Count multiple events as a single event"
            data-attr={`show-prop-combine-${index}`}
            noPadding
            onClick={() => {
                convertFilterToGroup(index)
                posthog.capture('combine_events', {
                    insight_type: insightType,
                    team_id: currentTeamId,
                })
            }}
            tooltip="Combine events"
            tooltipDocLink={inlineEventsDocLink}
        />
    )

    const deleteButton = (
        <LemonButton
            key="delete"
            icon={<IconTrash />}
            title="Delete graph series"
            data-attr={`delete-prop-filter-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                onClose()
            }}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Delete' : undefined}
        </LemonButton>
    )

    const rowStartElements = [
        sortable && filterCount > 1 ? <DragHandle key="drag-handle" listeners={listeners} /> : null,
        showSeriesIndicator && <div key="series-indicator">{seriesIndicator}</div>,
    ].filter(Boolean)

    // Check if popup would have any menu items (excluding filter and combine buttons which are always outside the menu)
    const hasMenuItems =
        isFunnelContext || !hideRename || (!hideDuplicate && !singleFilter) || (!hideDeleteBtn && !singleFilter)
    const showPopupMenu = !readOnly && enablePopup && hasMenuItems

    // When not using popup, show elements inline
    const rowEndElements =
        !readOnly && !showPopupMenu
            ? [
                  !hideFilter && propertyFiltersButton,
                  canCombine && combineInlineButton,
                  !hideRename && renameRowButton,
                  !hideDuplicate && !singleFilter && duplicateRowButton,
                  !hideDeleteBtn && !singleFilter && deleteButton,
              ].filter(Boolean)
            : []

    return (
        <li
            className="ActionFilterRow relative"
            ref={setNodeRef}
            {...attributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
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
                            <div className="flex-1 min-w-36 overflow-hidden">{filterElement}</div>
                            {customRowSuffix !== undefined && <>{suffix}</>}
                            {mathAvailability !== MathAvailability.None &&
                                mathAvailability !== MathAvailability.FunnelsOnly && (
                                    <>
                                        {mathAvailability !== MathAvailability.BoxPlotOnly && (
                                            <MathSelector
                                                math={math}
                                                mathGroupTypeIndex={mathGroupTypeIndex}
                                                index={index}
                                                onMathSelect={onMathSelect}
                                                disabled={readOnly}
                                                style={{ maxWidth: '100%', width: 'initial' }}
                                                mathAvailability={mathAvailability}
                                                trendsDisplayCategory={trendsDisplayCategory}
                                                allowedMathTypes={allowedMathTypes}
                                                query={query || {}}
                                            />
                                        )}
                                        {mathAvailability === MathAvailability.BoxPlotOnly && (
                                            <BoxPlotPropertySelector
                                                mathPropertyType={mathPropertyType}
                                                mathProperty={mathProperty}
                                                index={index}
                                                onMathPropertySelect={onMathPropertySelect}
                                                mathName={name}
                                            />
                                        )}
                                        {mathAvailability !== MathAvailability.BoxPlotOnly &&
                                            mathDefinitions[math || BaseMathType.TotalCount]?.category ===
                                                MathCategory.PropertyValue && (
                                                <PropertyValueMathSelector
                                                    mathPropertyType={mathPropertyType}
                                                    mathProperty={mathProperty}
                                                    mathName={name}
                                                    index={index}
                                                    onMathPropertySelect={onMathPropertySelect}
                                                    showNumericalPropsOnly={showNumericalPropsOnly}
                                                    schemaColumns={
                                                        filter.type == TaxonomicFilterGroupType.DataWarehouse &&
                                                        filter.name
                                                            ? Object.values(
                                                                  dataWarehouseTablesMap[filter.name]?.fields ?? []
                                                              )
                                                            : []
                                                    }
                                                    mathDisplayName={mathDefinitions[math ?? '']?.name.toLowerCase()}
                                                />
                                            )}
                                        {mathDefinitions[math || BaseMathType.TotalCount]?.category ===
                                            MathCategory.HogQLExpression && (
                                            <HogQLMathEditorDropdown
                                                mathHogQL={mathHogQL}
                                                index={index}
                                                onMathHogQLSelect={onMathHogQLSelect}
                                            />
                                        )}
                                    </>
                                )}
                        </div>
                        {/* right section fixed */}
                        {(rowEndElements.length > 0 || showPopupMenu) && (
                            <div className="ActionFilterRow__end">
                                {showPopupMenu ? (
                                    <>
                                        {!hideFilter && propertyFiltersButton}
                                        {canCombine && combineInlineButton}
                                        <ActionFilterRowMenu
                                            index={index}
                                            isTrendsContext={isTrendsContext}
                                            isFunnelContext={isFunnelContext}
                                            isStepOptional={isStepOptional}
                                            math={math}
                                            mathGroupTypeIndex={mathGroupTypeIndex}
                                            mathAvailability={mathAvailability}
                                            trendsDisplayCategory={trendsDisplayCategory}
                                            readOnly={readOnly}
                                            query={query || {}}
                                            filter={filter}
                                            hideRename={!!hideRename}
                                            hideDuplicate={hideDuplicate}
                                            hideDeleteBtn={hideDeleteBtn}
                                            singleFilter={!!singleFilter}
                                            onMathSelect={onMathSelect}
                                            onUpdateOptional={(checked) => {
                                                updateFilterOptional({
                                                    ...filter,
                                                    optionalInFunnel: checked,
                                                    index,
                                                })
                                            }}
                                            renameRowButton={renameRowButton}
                                            duplicateRowButton={duplicateRowButton}
                                            deleteButton={deleteButton}
                                        />
                                    </>
                                ) : (
                                    rowEndElements
                                )}
                            </div>
                        )}
                    </>
                )}
            </div>

            {propertyFiltersVisible && (
                <div className={`ActionFilterRow-filters${filtersLeftPadding ? ' pl-7' : ''}`}>
                    <PropertyFilters
                        pageKey={`${index}-${value}-${typeKey}-filter`}
                        propertyFilters={filter.properties}
                        onChange={onPropertyChange}
                        showNestedArrow={showNestedArrow}
                        disablePopover={!propertyFiltersPopover}
                        metadataSource={
                            filter.type == TaxonomicFilterGroupType.DataWarehouse
                                ? {
                                      kind: NodeKind.HogQLQuery,
                                      query: `select ${filter.aggregation_target_field} from ${filter.table_name}`,
                                  }
                                : undefined
                        }
                        taxonomicGroupTypes={
                            filter.type == TaxonomicFilterGroupType.DataWarehouse
                                ? [
                                      TaxonomicFilterGroupType.DataWarehouseProperties,
                                      TaxonomicFilterGroupType.HogQLExpression,
                                  ]
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
                        dataWarehouseTableName={
                            filter.type == TaxonomicFilterGroupType.DataWarehouse
                                ? (filter.name ?? undefined)
                                : undefined
                        }
                        addFilterDocLink={addFilterDocLink}
                        excludedProperties={excludedProperties}
                        hogQLGlobals={hogQLGlobals}
                        operatorAllowlist={operatorAllowlist}
                    />
                </div>
            )}
        </li>
    )
}
