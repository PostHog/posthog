import './ActionFilter.scss'

import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useEffect, useMemo } from 'react'

import { IconPlusSmall } from '@posthog/icons'

import {
    DataWarehousePopoverField,
    DefinitionPopoverRenderer,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopoverProps } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { DISPLAY_TYPES_TO_CATEGORIES as DISPLAY_TYPES_TO_CATEGORY } from 'lib/constants'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { verticalSortableListCollisionDetection } from 'lib/sortable'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { RenameModal } from 'scenes/insights/filters/ActionFilter/RenameModal'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

import { EventsNode } from '~/queries/schema/schema-general'
import { ChartDisplayCategory, ChartDisplayType, FilterType, InsightType, PropertyOperator } from '~/types'

import { ActionFilterGroup } from './ActionFilterGroup/ActionFilterGroup'
import { ActionFilterRow } from './ActionFilterRow/ActionFilterRow'
import { MathAvailability } from './ActionFilterRow/types'
import { LocalSeries, entityFilterLogic } from './entityFilterLogic'
import { legacyFiltersToSeries, seriesToLegacyFilters } from './legacyFilters'
import { SeriesNode, WarehouseSeriesNodeKind, isGroupSeriesNode } from './seriesNode'

export interface SeriesActionFilterProps {
    series: SeriesNode[]
    onChange: (series: SeriesNode[]) => void
    typeKey: string
    dataWarehouseNodeKind?: WarehouseSeriesNodeKind
    /** Fields a new series starts with, on top of the project's default event. */
    newSeriesDefaults?: Partial<EventsNode>
    /** Drives combine availability, the rename modal title, the limit copy and the docs link. */
    insightType?: InsightType
    /** Whether the insight has a breakdown, which changes the series letter colours. */
    hasBreakdown?: boolean
    /** Display category of the trends chart, or null outside a trends context. */
    trendsDisplayCategory?: ChartDisplayCategory | null
    mathAvailability?: MathAvailability
    /** Text copy for the action button to add more events/actions (graph series) */
    buttonCopy?: string
    buttonType?: LemonButtonProps['type']
    buttonProps?: LemonButtonProps
    /** Whether the full control is enabled or not */
    disabled?: boolean
    /** Bordered view */
    bordered?: boolean
    /** Whether actions/events can be sorted (used mainly for funnel step reordering) */
    sortable?: boolean
    /** Whether to show an indicator identifying each graph */
    showSeriesIndicator?: boolean
    /** Series badge shows A, B, C | 1, 2, 3 */
    seriesIndicatorType?: 'alpha' | 'numeric'
    /** Hide local filtering (currently used for retention insight) */
    hideFilter?: boolean
    /** Hides the rename option */
    hideRename?: boolean
    /** Hides the duplicate option */
    hideDuplicate?: boolean
    /** Whether to show the nested PropertyFilters in popover mode or not */
    propertyFiltersPopover?: boolean
    /** Opt in the flag-gated "Performed event" behavioral filter on each series. Only insight
     * query contexts should enable it — realtime contexts (CDP, workflows) reject behavioral filters. */
    allowBehavioralPropertyFilter?: boolean
    /** A limit of entities (series or funnel steps) beyond which more can't be added */
    entitiesLimit?: number
    /** Custom suffix element to show in each ActionFilterRow */
    customRowSuffix?:
        | string
        | JSX.Element
        | ((props: { node: SeriesNode; index: number; onClose: () => void }) => JSX.Element)
    /** Show nested arrows to the left of property filter buttons */
    showNestedArrow?: boolean
    /** Which tabs to show for actions selector */
    actionsTaxonomicGroupTypes?: TaxonomicFilterGroupType[]
    /** Which tabs to show for property filters */
    propertiesTaxonomicGroupTypes?: TaxonomicFilterGroupType[]
    /** Whether properties shown should be limited to just numerical types */
    showNumericalPropsOnly?: boolean
    hideDeleteBtn?: boolean | ((node: SeriesNode, index: number) => boolean)
    readOnly?: boolean
    renderRow?: ({
        seriesIndicator,
        prefix,
        filter,
        suffix,
        propertyFiltersButton,
        deleteButton,
        orLabel,
    }: Record<string, JSX.Element | string | undefined>) => JSX.Element
    /** Only allow these math types in the selector */
    allowedMathTypes?: readonly string[]
    /** Data warehouse popover fields */
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
    /** Whether to add left padding to the filters div to align with indented content */
    filtersLeftPadding?: boolean
    /** Doc link to show in the tooltip of the New Filter button */
    addFilterDocLink?: string
    /** Properties to exclude from the properties filter */
    excludedProperties?: TaxonomicPopoverProps['excludedProperties']
    includeHiddenEvents?: TaxonomicPopoverProps['includeHiddenEvents']
    /** Allow adding non-captured events */
    allowNonCapturedEvents?: boolean
    hogQLGlobals?: Record<string, any>
    definitionPopoverRenderer?: DefinitionPopoverRenderer
    operatorAllowlist?: PropertyOperator[]
    /** Extra content rendered in the footer alongside the "Add series" button */
    customFooter?: React.ReactNode
}

export const SeriesActionFilter = React.forwardRef<HTMLDivElement, SeriesActionFilterProps>(function SeriesActionFilter(
    {
        series,
        onChange,
        typeKey,
        dataWarehouseNodeKind,
        newSeriesDefaults,
        insightType,
        hasBreakdown = false,
        trendsDisplayCategory = null,
        mathAvailability = MathAvailability.All,
        buttonCopy = '',
        buttonProps = {},
        disabled = false,
        sortable = false,
        showSeriesIndicator = false,
        seriesIndicatorType = 'alpha',
        hideFilter = false,
        hideRename = false,
        hideDuplicate = false,
        propertyFiltersPopover,
        allowBehavioralPropertyFilter,
        customRowSuffix,
        entitiesLimit,
        showNestedArrow = false,
        actionsTaxonomicGroupTypes,
        propertiesTaxonomicGroupTypes,
        showNumericalPropsOnly,
        hideDeleteBtn,
        renderRow,
        buttonType = 'tertiary',
        readOnly = false,
        bordered = false,
        allowedMathTypes,
        dataWarehousePopoverFields,
        filtersLeftPadding,
        addFilterDocLink,
        excludedProperties,
        includeHiddenEvents,
        allowNonCapturedEvents,
        hogQLGlobals,
        definitionPopoverRenderer,
        operatorAllowlist,
        customFooter,
    },
    ref
): JSX.Element {
    const logicProps = {
        series,
        onChange,
        typeKey,
        newSeriesDefaults,
        dataWarehousePopoverFields,
        dataWarehouseNodeKind,
    }
    const logic = entityFilterLogic(logicProps)
    const { reportFunnelStepReordered } = useActions(eventUsageLogic)

    const { localSeries } = useValues(logic)
    const { addSeries, setSeries } = useActions(logic)

    // No way around this. Somehow the ordering of the logic calling each other causes stale
    // series to be shown on the /funnels page, even if we try to use a selector with props
    // to hydrate it
    useEffect(() => {
        setSeries(series)
    }, [series]) // oxlint-disable-line react-hooks/exhaustive-deps

    function onSortEnd({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void {
        function move(arr: LocalSeries[], from: number, to: number): LocalSeries[] {
            const clone = [...arr]
            Array.prototype.splice.call(clone, to, 0, Array.prototype.splice.call(clone, from, 1)[0])
            return clone
        }
        onChange(move(localSeries, oldIndex, newIndex).map(({ node }) => node))
        if (oldIndex !== newIndex) {
            reportFunnelStepReordered()
        }
    }

    const singleFilter = entitiesLimit === 1
    const canAccessEventsCombination = insightType === InsightType.TRENDS || insightType === InsightType.FUNNELS
    // A filter object with no `insight` reads as trends, so an absent insight type does too.
    const isTrendsInsight = insightType === InsightType.TRENDS || insightType === undefined

    const commonProps = {
        logic,
        showSeriesIndicator,
        seriesIndicatorType,
        mathAvailability,
        customRowSuffix,
        hasBreakdown,
        trendsDisplayCategory,
        actionsTaxonomicGroupTypes,
        propertiesTaxonomicGroupTypes,
        propertyFiltersPopover,
        allowBehavioralPropertyFilter,
        disabled,
        readOnly,
        renderRow,
        hideRename,
        hideDuplicate,
        showCombine: canAccessEventsCombination,
        insightType,
        onRenameClick: logic.actions.showModal,
        sortable,
        showNumericalPropsOnly,
        allowedMathTypes,
        dataWarehousePopoverFields,
        dataWarehouseNodeKind,
        filtersLeftPadding,
        addFilterDocLink,
        excludedProperties,
        includeHiddenEvents,
        allowNonCapturedEvents,
        hogQLGlobals,
        operatorAllowlist,
        inlineEventsDocLink: isTrendsInsight
            ? 'https://posthog.com/docs/product-analytics/trends/overview#combine-events-inline'
            : 'https://posthog.com/docs/product-analytics/funnels#combine-events-inline',
    }

    const reachedLimit: boolean = Boolean(entitiesLimit && localSeries.length >= entitiesLimit)
    const sortedItemIds = localSeries.map((i) => i.uuid)

    return (
        <div
            className={clsx('ActionFilter', {
                'ActionFilter--bordered': bordered,
            })}
            ref={ref}
        >
            {!hideRename && !readOnly && (
                <BindLogic logic={entityFilterLogic} props={logicProps}>
                    <RenameModal view={insightType} typeKey={typeKey} />
                </BindLogic>
            )}
            {localSeries ? (
                <ul>
                    <DndContext
                        onDragEnd={({ active, over }) => {
                            if (over && active.id !== over.id) {
                                onSortEnd({
                                    oldIndex: sortedItemIds.indexOf(active.id.toString()),
                                    newIndex: sortedItemIds.indexOf(over.id.toString()),
                                })
                            }
                        }}
                        modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                        collisionDetection={verticalSortableListCollisionDetection}
                    >
                        <SortableContext
                            disabled={!sortable}
                            items={sortedItemIds}
                            strategy={verticalListSortingStrategy}
                        >
                            {localSeries.map(({ uuid, node }, index) =>
                                canAccessEventsCombination && isGroupSeriesNode(node) ? (
                                    <ActionFilterGroup
                                        key={uuid}
                                        node={node}
                                        uuid={uuid}
                                        index={index}
                                        typeKey={typeKey}
                                        filterCount={localSeries.length}
                                        sortable={sortable}
                                        showSeriesIndicator={showSeriesIndicator}
                                        seriesIndicatorType={seriesIndicatorType}
                                        disabled={disabled}
                                        readOnly={readOnly}
                                        hideDeleteBtn={
                                            typeof hideDeleteBtn === 'function'
                                                ? hideDeleteBtn(node, index)
                                                : hideDeleteBtn
                                        }
                                        hasBreakdown={hasBreakdown}
                                        mathAvailability={mathAvailability}
                                        groupTitle={node.custom_name || 'Any of the events below'}
                                        actionsTaxonomicGroupTypes={actionsTaxonomicGroupTypes}
                                        dataWarehousePopoverFields={dataWarehousePopoverFields}
                                        excludedProperties={excludedProperties}
                                        includeHiddenEvents={includeHiddenEvents}
                                        insightType={insightType}
                                        definitionPopoverRenderer={definitionPopoverRenderer}
                                    />
                                ) : (
                                    <ActionFilterRow
                                        key={uuid}
                                        typeKey={typeKey}
                                        node={node}
                                        uuid={uuid}
                                        index={index}
                                        filterCount={localSeries.length}
                                        showNestedArrow={showNestedArrow}
                                        singleFilter={singleFilter}
                                        hideFilter={hideFilter || readOnly}
                                        hideDeleteBtn={
                                            typeof hideDeleteBtn === 'function'
                                                ? hideDeleteBtn(node, index)
                                                : hideDeleteBtn
                                        }
                                        definitionPopoverRenderer={definitionPopoverRenderer}
                                        {...commonProps}
                                    />
                                )
                            )}
                        </SortableContext>
                    </DndContext>
                </ul>
            ) : null}
            {!singleFilter && (
                <div className="ActionFilter-footer">
                    <LemonButton
                        type={buttonType}
                        onClick={() => addSeries()}
                        data-attr="add-action-event-button"
                        icon={<IconPlusSmall />}
                        size="small"
                        disabled={reachedLimit || disabled || readOnly}
                        {...buttonProps}
                    >
                        {!reachedLimit
                            ? buttonCopy || 'Action or event'
                            : `Reached limit of ${entitiesLimit} ${
                                  insightType === InsightType.FUNNELS ? 'steps' : 'series'
                              }`}
                    </LemonButton>
                    {customFooter}
                </div>
            )}
        </div>
    )
})

export interface ActionFilterProps extends Omit<
    SeriesActionFilterProps,
    'series' | 'onChange' | 'insightType' | 'hasBreakdown' | 'trendsDisplayCategory' | 'newSeriesDefaults'
> {
    setFilters: (filters: FilterType) => void
    filters: FilterType
    addFilterDefaultOptions?: Record<string, any>
}

/**
 * The legacy entity filter shape, for the surfaces that persist it on a backend or schema
 * contract. Everything else renders `SeriesActionFilter` and keeps its query nodes.
 */
export const ActionFilter = React.forwardRef<HTMLDivElement, ActionFilterProps>(function ActionFilter(
    { setFilters, filters, addFilterDefaultOptions, dataWarehouseNodeKind, ...rest },
    ref
): JSX.Element {
    const series = useMemo(
        () => legacyFiltersToSeries(filters, dataWarehouseNodeKind),
        [filters, dataWarehouseNodeKind]
    )

    return (
        <SeriesActionFilter
            {...rest}
            ref={ref}
            series={series}
            onChange={(nextSeries) => setFilters(seriesToLegacyFilters(nextSeries))}
            dataWarehouseNodeKind={dataWarehouseNodeKind}
            newSeriesDefaults={addFilterDefaultOptions}
            insightType={filters.insight}
            hasBreakdown={!!filters.breakdown}
            trendsDisplayCategory={
                isTrendsFilter(filters)
                    ? DISPLAY_TYPES_TO_CATEGORY[filters.display || ChartDisplayType.ActionsLineGraph]
                    : null
            }
        />
    )
})
