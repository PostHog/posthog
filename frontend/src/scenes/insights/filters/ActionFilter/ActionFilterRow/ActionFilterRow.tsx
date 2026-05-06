import './ActionFilterRow.scss'

import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback } from 'react'

import {
    IconChevronDown,
    IconCopy,
    IconFilter,
    IconGroupIntersect,
    IconInfo,
    IconPencil,
    IconTrash,
} from '@posthog/icons'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { SeriesGlyph, SeriesLetter } from 'lib/components/SeriesGlyph'
import { TaxonomicAutocomplete, TaxonomicFilterHeadless } from 'lib/components/TaxonomicFilter/headless'
import { MenuFilterEntry, TaxonomicFilterMenu } from 'lib/components/TaxonomicFilter/menu'
import { defaultDataWarehousePopoverFields } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    DataWarehousePopoverField,
    TaxonomicFilterGroupType,
    isQuickFilterItem,
    quickFilterToPropertyFilters,
} from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover, TaxonomicPopoverProps } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount, SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
import { BoxPlotPropertySelector } from './BoxPlotPropertySelector'
import { HogQLMathEditorDropdown } from './HogQLMathEditor'
import { MathSelector } from './MathSelector'
import { getDefaultMathHogQLExpression } from './mathUtils'
import { PropertyValueMathSelector } from './PropertyValueMathSelector'
import { SaveAsActionBanner } from './SaveAsActionBanner'
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
    const { featureFlags } = useValues(featureFlagLogic)
    const useMenuRebuild = !!featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]

    const mountedInsightDataLogic = insightDataLogic.findMounted({ dashboardItemId: typeKey })
    const query = mountedInsightDataLogic?.values?.query

    const isFunnelContext = mathAvailability === MathAvailability.FunnelsOnly
    const isTrendsContext = trendsDisplayCategory != null
    const suggestedFiltersLabel = isFunnelContext ? 'Suggested step' : isTrendsContext ? 'Suggested series' : undefined

    // Always call hooks for React compliance - provide safe defaults for non-funnel contexts
    // dashboardItemId should be the insight's id, but the typeKey might contain a /on-dashboard- suffix
    const dashboardItemId = typeKey.split('/')[0] as InsightShortId
    const { insightProps: funnelInsightProps } = useValues(
        insightLogic({ dashboardItemId: isFunnelContext ? dashboardItemId : 'new' })
    )
    const { isStepOptional: funnelIsStepOptional } = useValues(funnelDataLogic(funnelInsightProps))

    // Only use the funnel results when in funnel context
    const isStepOptional = isFunnelContext ? funnelIsStepOptional : () => false

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
    const defaultMathHogQLExpression = getDefaultMathHogQLExpression(insightType)

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
                    ? (mathHogQL ?? defaultMathHogQLExpression)
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

    const isDataWarehouseFilter = filter.type === EntityTypes.DATA_WAREHOUSE
    const initialGroupType = isDataWarehouseFilter
        ? TaxonomicFilterGroupType.DataWarehouse
        : TaxonomicFilterGroupType.SuggestedFilters

    // DWH events are not supported in inline events yet
    const canCombine = showCombine && !singleFilter && !isDataWarehouseFilter

    const filterElement = (
        <TaxonomicPopover
            data-attr={'trend-element-subject-' + index}
            fullWidth
            truncate
            groupType={initialGroupType}
            value={getValue(value, filter)}
            filter={filter}
            suggestedFiltersLabel={suggestedFiltersLabel}
            enableKeywordShortcuts
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
            renderValue={() => <EntityFilterInfo filter={filter} showIcon />}
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
            data-attr={`show-prop-combine-${index}`}
            noPadding={!enablePopup}
            onClick={() => {
                convertFilterToGroup(index)
                posthog.capture('combine_events', {
                    insight_type: insightType,
                    team_id: currentTeamId,
                })
            }}
            tooltip="Count multiple events as a single event"
            tooltipDocLink={inlineEventsDocLink}
            fullWidth={enablePopup}
        >
            {enablePopup ? 'Combine' : undefined}
        </LemonButton>
    )

    const deleteButton = (
        <LemonButton
            key="delete"
            status={enablePopup ? 'danger' : 'default'}
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

    // Check if popup would have any menu items (excluding filter button which is always outside the menu)
    const hasMenuItems =
        isFunnelContext ||
        !hideRename ||
        (!hideDuplicate && !singleFilter) ||
        (!hideDeleteBtn && !singleFilter) ||
        canCombine
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
            className="ActionFilterRow relative @max-[400px]/editor-panel:border @max-[400px]/editor-panel:rounded @max-[400px]/editor-panel:p-2"
            ref={setNodeRef}
            {...attributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div className="ActionFilterRow-content @max-[400px]/editor-panel:flex-wrap @max-[400px]/editor-panel:gap-2 @max-[400px]/editor-panel:w-full @max-[400px]/editor-panel:items-center @max-[400px]/editor-panel:justify-between @max-[400px]/editor-panel:[&>*+*]:ml-0">
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
                            <div className="ActionFilterRow__start @max-[400px]/editor-panel:[height:auto]">
                                {rowStartElements}
                            </div>
                        ) : null}
                        {/* central section flexible */}
                        <div
                            className={clsx(
                                'ActionFilterRow__center',
                                rowStartElements.length > 0 &&
                                    '@max-[400px]/editor-panel:basis-full @max-[400px]/editor-panel:order-1 @max-[400px]/editor-panel:min-w-0 @max-[400px]/editor-panel:[&>*]:basis-full'
                            )}
                        >
                            <div className="flex-1 min-w-36 overflow-hidden">{filterElement}</div>
                            {/* Production-testing variant: the new
                                TaxonomicFilterMenu (column / preview-pane
                                view) renders alongside the legacy
                                TaxonomicPopover so we can ramp it as the
                                series-row picker. */}
                            <div
                                className="flex-1 min-w-36 overflow-hidden"
                                data-attr={`series-parity-autocomplete-${index}`}
                            >
                                <TaxonomicFilterHeadless.Root
                                    // Skip the legacy rootProps wrapper —
                                    // its onKeyDown intercepts Tab/Arrow
                                    // for the old list UI we don't render
                                    // here, and traps Tab off the trigger.
                                    bindRootProps={false}
                                    taxonomicGroupTypes={effectiveActionsTaxonomicGroupTypes}
                                    onChange={(group, changedValue, item) => {
                                        const groupType = taxonomicFilterGroupTypeToEntityType(group.type)
                                        if (!groupType) {
                                            return
                                        }
                                        updateFilter({
                                            type: groupType,
                                            id: changedValue ? String(changedValue) : null,
                                            name: item?.name ?? '',
                                            index,
                                        })
                                    }}
                                >
                                    {useMenuRebuild ? (
                                        <TaxonomicFilterMenu
                                            triggerLabel="All events"
                                            comboboxTitle="Choose series filter"
                                            // Synthetic entry — the menu only
                                            // reads `group.type` (to route
                                            // the initial open) and `name` /
                                            // `friendlyLabel` (for the
                                            // trigger label). A full
                                            // `TaxonomicFilterGroup` isn't
                                            // needed here.
                                            selected={
                                                filter.id != null && filter.type
                                                    ? ({
                                                          // DWH filters need the saved column
                                                          // mapping (`id_field` /
                                                          // `timestamp_field` /
                                                          // `distinct_id_field` etc.) on the
                                                          // `item` so re-opening the menu
                                                          // routes into `dwh-config` with the
                                                          // form pre-filled. Spread the whole
                                                          // filter for DWH; events/actions
                                                          // only need id + name.
                                                          item:
                                                              filter.type === EntityTypes.DATA_WAREHOUSE
                                                                  ? {
                                                                        ...filter,
                                                                        name: filter.name,
                                                                        // DWH `getValue` reads `name`,
                                                                        // not `id` — make sure both
                                                                        // are present so routing +
                                                                        // checkmark match.
                                                                        ...dataWarehouseTablesMap[String(filter.name)],
                                                                    }
                                                                  : { id: filter.id, name: filter.name },
                                                          group: {
                                                              type:
                                                                  filter.type === EntityTypes.ACTIONS
                                                                      ? TaxonomicFilterGroupType.Actions
                                                                      : filter.type === EntityTypes.DATA_WAREHOUSE
                                                                        ? TaxonomicFilterGroupType.DataWarehouse
                                                                        : TaxonomicFilterGroupType.Events,
                                                              // DWH config form reads `getName`
                                                              // / `getValue` off `selected.group`
                                                              // when re-opening, so provide them
                                                              // for the DWH branch. Events /
                                                              // Actions don't need them — the
                                                              // resolved orchestrator group is
                                                              // used for those once the user
                                                              // commits.
                                                              getName: (t: any) => t?.name,
                                                              getValue: (t: any) => t?.name,
                                                          },
                                                          name: String(name ?? filter.id),
                                                          friendlyLabel: name ? String(name) : undefined,
                                                      } as unknown as MenuFilterEntry)
                                                    : null
                                            }
                                            trigger={({ selected, label, open }) => (
                                                <div className="relative border border-dashed border-accent p-1 rounded-sm">
                                                    <LemonButton
                                                        type="secondary"
                                                        fullWidth
                                                        data-attr={`series-parity-autocomplete-trigger-${index}`}
                                                        aria-expanded={open}
                                                        sideIcon={<IconChevronDown />}
                                                    >
                                                        {selected ? (
                                                            <EntityFilterInfo filter={filter} showIcon />
                                                        ) : (
                                                            <span className="text-secondary">{label}</span>
                                                        )}
                                                    </LemonButton>
                                                    <div className="absolute -top-1 -right-1">
                                                        <Tooltip
                                                            title={
                                                                <>
                                                                    INTERNAL ONLY
                                                                    <br />
                                                                    The new TaxonomicFilterMenu. <br />
                                                                    Try it out, leave feedback/wishlist!
                                                                    <br />
                                                                    Owned by <b>#platform-ux</b>
                                                                </>
                                                            }
                                                        >
                                                            <IconInfo className="size-4 text-accent bg-surface-primary" />
                                                        </Tooltip>
                                                    </div>
                                                </div>
                                            )}
                                        />
                                    ) : (
                                        <TaxonomicAutocomplete.Root
                                            key={`${filter.type}:${String(filter.id ?? '')}`}
                                            triggerLabel="All events"
                                            defaultSelected={
                                                filter.id != null && filter.type
                                                    ? {
                                                          groupType:
                                                              filter.type === EntityTypes.ACTIONS
                                                                  ? TaxonomicFilterGroupType.Actions
                                                                  : TaxonomicFilterGroupType.Events,
                                                          value: value ?? null,
                                                          name: String(name ?? filter.id),
                                                          friendlyLabel: name ? String(name) : undefined,
                                                      }
                                                    : null
                                            }
                                        >
                                            <TaxonomicAutocomplete.Popover>
                                                <TaxonomicAutocomplete.Trigger>
                                                    {({ selected, label, open }) => (
                                                        <LemonButton
                                                            type="secondary"
                                                            fullWidth
                                                            data-attr={`series-parity-autocomplete-trigger-${index}`}
                                                            aria-expanded={open}
                                                            sideIcon={<IconChevronDown />}
                                                        >
                                                            {selected ? (
                                                                <EntityFilterInfo filter={filter} showIcon />
                                                            ) : (
                                                                <span className="text-secondary">{label}</span>
                                                            )}
                                                        </LemonButton>
                                                    )}
                                                </TaxonomicAutocomplete.Trigger>
                                                <TaxonomicAutocomplete.Content>
                                                    <TaxonomicAutocomplete.Header rootTitle="Pick event or action" />
                                                    <TaxonomicAutocomplete.RootView>
                                                        <div className="p-1">
                                                            <TaxonomicAutocomplete.Input />
                                                        </div>
                                                        <TaxonomicAutocomplete.Chips />
                                                        <TaxonomicAutocomplete.List />
                                                    </TaxonomicAutocomplete.RootView>
                                                </TaxonomicAutocomplete.Content>
                                            </TaxonomicAutocomplete.Popover>
                                        </TaxonomicAutocomplete.Root>
                                    )}
                                </TaxonomicFilterHeadless.Root>
                            </div>
                            {customRowSuffix !== undefined && <>{suffix}</>}
                            {mathAvailability !== MathAvailability.None &&
                                mathAvailability !== MathAvailability.FunnelsOnly && (
                                    <>
                                        {mathAvailability !== MathAvailability.BoxPlotOnly && (
                                            <div className="@min-[0px]/editor-panel:shrink @min-[0px]/editor-panel:min-w-28 @min-[0px]/editor-panel:overflow-hidden">
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
                                                    fullWidth
                                                    truncateText={{ maxWidthClass: 'max-w-full' }}
                                                />
                                            </div>
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
                                                    mathPropertyType={
                                                        mathPropertyType ||
                                                        (isDataWarehouseFilter
                                                            ? TaxonomicFilterGroupType.DataWarehouseProperties
                                                            : TaxonomicFilterGroupType.NumericalEventProperties)
                                                    }
                                                    mathPropertyTypes={
                                                        isDataWarehouseFilter
                                                            ? [TaxonomicFilterGroupType.DataWarehouseProperties]
                                                            : [
                                                                  TaxonomicFilterGroupType.NumericalEventProperties,
                                                                  TaxonomicFilterGroupType.SessionProperties,
                                                                  TaxonomicFilterGroupType.PersonProperties,
                                                                  TaxonomicFilterGroupType.DataWarehousePersonProperties,
                                                              ]
                                                    }
                                                    mathProperty={mathProperty}
                                                    mathName={name}
                                                    index={index}
                                                    onMathPropertySelect={onMathPropertySelect}
                                                    showNumericalPropsOnly={showNumericalPropsOnly}
                                                    schemaColumns={
                                                        isDataWarehouseFilter && filter.name
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
                            <div className="ActionFilterRow__end @max-[400px]/editor-panel:gap-1 @max-[400px]/editor-panel:[height:auto]">
                                {showPopupMenu ? (
                                    <>
                                        {!hideFilter && propertyFiltersButton}
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
                                            combineButton={canCombine ? combineInlineButton : null}
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
                            isDataWarehouseFilter
                                ? {
                                      kind: NodeKind.HogQLQuery,
                                      query: `select ${filter.aggregation_target_field} from ${filter.table_name}`,
                                  }
                                : undefined
                        }
                        taxonomicGroupTypes={
                            isDataWarehouseFilter
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
                            isDataWarehouseFilter && filter.name
                                ? Object.values(dataWarehouseTablesMap[filter.name]?.fields ?? [])
                                : []
                        }
                        dataWarehouseTableName={isDataWarehouseFilter ? (filter.name ?? undefined) : undefined}
                        addFilterDocLink={addFilterDocLink}
                        excludedProperties={excludedProperties}
                        hogQLGlobals={hogQLGlobals}
                        operatorAllowlist={operatorAllowlist}
                    />
                    <SaveAsActionBanner filter={filter} />
                </div>
            )}
        </li>
    )
}
