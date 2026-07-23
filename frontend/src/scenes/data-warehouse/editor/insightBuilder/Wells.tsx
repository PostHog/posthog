import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconGear } from '@posthog/icons'
import { LemonDialog, LemonTabs, Popover } from '@posthog/lemon-ui'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { cn } from 'lib/utils/css-classes'

import { YSeriesDisplayTab, YSeriesFormattingTab } from '~/queries/nodes/DataVisualization/Components/SeriesTab'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import {
    AGGREGATION_LABELS,
    DATE_GRAIN_LABELS,
    DATE_GRAIN_OPTIONS,
    FILTER_OPERATOR_LABELS,
    NON_NUMERIC_AGGREGATIONS,
    NUMERIC_AGGREGATIONS,
    filterOperatorsForField,
    operatorNeedsValue,
} from '~/queries/nodes/DataVisualization/insightBuilder/builderLabels'
import {
    BuilderWell,
    getChartCapability,
    isWellEnabled,
} from '~/queries/nodes/DataVisualization/insightBuilder/chartCapabilities'
import {
    InsightBuilderAggregation,
    InsightBuilderDimension,
    InsightBuilderFilter,
    InsightBuilderMeasure,
} from '~/queries/schema/schema-general'

import { COUNT_STAR_COLUMN, insightBuilderLogic } from './insightBuilderLogic'

export function pillId(well: BuilderWell, index: number): string {
    return `pill:${well}:${index}`
}

export function parsePillId(id: string): { well: BuilderWell; index: number } | null {
    const match = /^pill:(rows|columns|values|filters):(\d+)$/.exec(id)
    return match ? { well: match[1] as BuilderWell, index: parseInt(match[2], 10) } : null
}

function PillMenu({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <button
                        type="button"
                        className="inline-flex cursor-pointer items-center gap-0.5 rounded px-1 text-xs text-secondary hover:bg-surface-secondary"
                        // Bubble phase (not capture): let the trigger open first, then stop the
                        // event before the pill's drag listeners on the parent see it
                        onPointerDown={(e) => e.stopPropagation()}
                    />
                }
            >
                {label}
                <IconChevronDown className="size-3" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">{children}</DropdownMenuContent>
        </DropdownMenu>
    )
}

function DimensionPill({
    tabId,
    well,
    index,
    dimension,
}: {
    tabId: string
    well: 'rows' | 'columns'
    index: number
    dimension: InsightBuilderDimension
}): JSX.Element {
    const { baseFields } = useValues(insightBuilderLogic({ tabId }))
    const { removeField, setDateGrain, setNumericBinWidth } = useActions(insightBuilderLogic({ tabId }))

    const field = baseFields.find((candidate) => candidate.name === dimension.column)
    const isDate = field?.isDate || !!dimension.dateGrain
    // A numeric column (that isn't a date) can be bucketed into fixed-width bins
    const isNumeric = !isDate && (field?.isNumerical ?? false)
    const isMissing = baseFields.length > 0 && !field

    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: pillId(well, index),
        data: { type: 'pill', well, index, item: dimension },
    })

    const openBinModal = (): void => {
        LemonDialog.openForm({
            title: `Bin ${dimension.column}`,
            description: 'Group values into fixed-width buckets, e.g. a width of 10 gives 0–10, 10–20, …',
            initialValues: { binWidth: dimension.numericBinWidth ?? 10 },
            content: (
                <LemonField name="binWidth" label="Bin width">
                    <LemonInput type="number" min={0} step="any" autoFocus />
                </LemonField>
            ),
            errors: {
                binWidth: (value) => (!value || Number(value) <= 0 ? 'Enter a width greater than 0' : undefined),
            },
            onSubmit: ({ binWidth }) => setNumericBinWidth(well, index, Number(binWidth)),
        })
    }

    return (
        <LemonSnack
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            onClose={() => removeField(well, index)}
            className={cn(
                'w-full cursor-grab justify-between',
                isDragging && 'opacity-50',
                isMissing && 'border border-danger'
            )}
            title={isMissing ? `"${dimension.column}" is not in the base query results anymore` : undefined}
            style={{ transform: CSS.Transform.toString(transform), transition }}
            data-attr="sql-builder-well-pill"
        >
            <span className="flex items-center gap-1">
                <span className="truncate">{dimension.column}</span>
                {isDate ? (
                    <PillMenu label={dimension.dateGrain ? DATE_GRAIN_LABELS[dimension.dateGrain] : 'Exact'}>
                        {DATE_GRAIN_OPTIONS.map((grain) => (
                            <DropdownMenuItem key={grain} onClick={() => setDateGrain(well, index, grain)}>
                                {DATE_GRAIN_LABELS[grain]}
                            </DropdownMenuItem>
                        ))}
                        <DropdownMenuItem onClick={() => setDateGrain(well, index, null)}>Exact value</DropdownMenuItem>
                    </PillMenu>
                ) : isNumeric ? (
                    <PillMenu label={dimension.numericBinWidth ? `Bins of ${dimension.numericBinWidth}` : 'Exact'}>
                        <DropdownMenuItem onClick={openBinModal}>Set bin width…</DropdownMenuItem>
                        <DropdownMenuItem onClick={() => setNumericBinWidth(well, index, null)}>
                            Exact value
                        </DropdownMenuItem>
                    </PillMenu>
                ) : null}
            </span>
        </LemonSnack>
    )
}

/**
 * Edit icon on a value pill that opens the field's Formatting/Display controls (number format,
 * color, label) in a popover — the per-series settings that used to live only in the Series tab.
 * Series map to Values by position; the icon is hidden until the query has produced that series.
 */
function FieldSettingsButton({ index }: { index: number }): JSX.Element | null {
    const { yData, dataVisualizationProps } = useValues(dataVisualizationLogic)
    const [open, setOpen] = useState(false)
    const [tab, setTab] = useState<'formatting' | 'display'>('formatting')

    const series = yData[index]
    if (!series) {
        return null
    }
    const seriesLogicProps = { series, seriesIndex: index, dataVisualizationProps }

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="right-start"
            overlay={
                <div className="w-72 p-2">
                    <LemonTabs
                        size="small"
                        activeKey={tab}
                        onChange={(key) => setTab(key as 'formatting' | 'display')}
                        tabs={[
                            {
                                key: 'formatting',
                                label: 'Formatting',
                                content: <YSeriesFormattingTab ySeriesLogicProps={seriesLogicProps} />,
                            },
                            {
                                key: 'display',
                                label: 'Display',
                                content: <YSeriesDisplayTab ySeriesLogicProps={seriesLogicProps} />,
                            },
                        ]}
                    />
                </div>
            }
        >
            <button
                type="button"
                className="ml-auto inline-flex shrink-0 cursor-pointer items-center rounded p-0.5 text-secondary hover:bg-surface-secondary"
                aria-label="Format this value"
                // Bubble phase: open the popover without engaging the pill's drag listeners
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => setOpen((previous) => !previous)}
                data-attr="sql-builder-value-settings"
            >
                <IconGear />
            </button>
        </Popover>
    )
}

function MeasurePill({
    tabId,
    index,
    measure,
}: {
    tabId: string
    index: number
    measure: InsightBuilderMeasure
}): JSX.Element {
    const { baseFields } = useValues(insightBuilderLogic({ tabId }))
    const { removeField, setAggregation } = useActions(insightBuilderLogic({ tabId }))

    const field = baseFields.find((candidate) => candidate.name === measure.column)
    const isCountOfRows = measure.column === COUNT_STAR_COLUMN
    const isMissing = baseFields.length > 0 && !isCountOfRows && !field
    const aggregations: InsightBuilderAggregation[] =
        field && !field.isNumerical ? NON_NUMERIC_AGGREGATIONS : NUMERIC_AGGREGATIONS

    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: pillId('values', index),
        data: { type: 'pill', well: 'values', index, item: measure },
    })

    return (
        <LemonSnack
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            onClose={() => removeField('values', index)}
            className={cn(
                'w-full cursor-grab justify-between',
                isDragging && 'opacity-50',
                isMissing && 'border border-danger'
            )}
            title={isMissing ? `"${measure.column}" is not in the base query results anymore` : undefined}
            style={{ transform: CSS.Transform.toString(transform), transition }}
            data-attr="sql-builder-well-pill"
        >
            <span className="flex w-full items-center gap-1">
                {isCountOfRows ? (
                    <span className="truncate">Count of rows</span>
                ) : (
                    <>
                        <PillMenu label={AGGREGATION_LABELS[measure.aggregation]}>
                            {aggregations.map((aggregation) => (
                                <DropdownMenuItem key={aggregation} onClick={() => setAggregation(index, aggregation)}>
                                    {AGGREGATION_LABELS[aggregation]}
                                </DropdownMenuItem>
                            ))}
                        </PillMenu>
                        <span className="truncate">of {measure.column}</span>
                    </>
                )}
                <FieldSettingsButton index={index} />
            </span>
        </LemonSnack>
    )
}

function FilterPill({
    tabId,
    index,
    filter,
}: {
    tabId: string
    index: number
    filter: InsightBuilderFilter
}): JSX.Element {
    const { baseFields } = useValues(insightBuilderLogic({ tabId }))
    const { removeField, updateFilter } = useActions(insightBuilderLogic({ tabId }))

    const field = baseFields.find((candidate) => candidate.name === filter.column)
    const isMissing = baseFields.length > 0 && !field
    const needsValue = operatorNeedsValue(filter.operator)
    const operators = filterOperatorsForField(field)
    // Numeric columns get a number input; the value still compiles as a literal ClickHouse coerces
    const isNumericValue = !!field?.isNumerical
    const valuePlaceholder = field?.isDate ? 'YYYY-MM-DD' : 'value'

    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: pillId('filters', index),
        data: { type: 'pill', well: 'filters', index, item: filter },
    })

    return (
        <LemonSnack
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            onClose={() => removeField('filters', index)}
            className={cn(
                'w-full cursor-grab justify-between',
                isDragging && 'opacity-50',
                isMissing && 'border border-danger'
            )}
            title={isMissing ? `"${filter.column}" is not in the base query results anymore` : undefined}
            style={{ transform: CSS.Transform.toString(transform), transition }}
            data-attr="sql-builder-well-pill"
        >
            <span className="flex w-full min-w-0 items-center gap-1">
                <span className="shrink truncate">{filter.column}</span>
                <PillMenu label={FILTER_OPERATOR_LABELS[filter.operator]}>
                    {operators.map((operator) => (
                        <DropdownMenuItem
                            key={operator}
                            onClick={() =>
                                updateFilter(
                                    index,
                                    operatorNeedsValue(operator) ? { operator } : { operator, value: undefined }
                                )
                            }
                        >
                            {FILTER_OPERATOR_LABELS[operator]}
                        </DropdownMenuItem>
                    ))}
                </PillMenu>
                {needsValue ? (
                    // Stop pointer events from reaching the drag listeners so text selection inside
                    // the input doesn't start a pill drag
                    <span className="min-w-0 flex-1" onPointerDownCapture={(e) => e.stopPropagation()}>
                        {isNumericValue ? (
                            <LemonInput
                                size="xsmall"
                                type="number"
                                placeholder="value"
                                value={filter.value != null && filter.value !== '' ? Number(filter.value) : undefined}
                                onChange={(value) => updateFilter(index, { value: value != null ? String(value) : '' })}
                                data-attr="sql-builder-filter-value"
                            />
                        ) : (
                            <LemonInput
                                size="xsmall"
                                placeholder={valuePlaceholder}
                                value={filter.value ?? ''}
                                onChange={(value) => updateFilter(index, { value })}
                                data-attr="sql-builder-filter-value"
                            />
                        )}
                    </span>
                ) : null}
            </span>
        </LemonSnack>
    )
}

function Well({
    well,
    title,
    emptyHint,
    children,
    count,
    canAddMore,
    disabled,
    disabledReason,
}: {
    well: BuilderWell
    title: string
    emptyHint: string
    children: React.ReactNode
    count: number
    /** The current chart accepts more fields in this well — show a "drop another" hint */
    canAddMore?: boolean
    disabled?: boolean
    disabledReason?: string
}): JSX.Element {
    const { setNodeRef, isOver } = useDroppable({
        id: `well:${well}`,
        data: { type: 'well', well },
        disabled,
    })

    // A drop into a full well (no remaining capacity) replaces the existing field rather than adding
    const isFull = !disabled && !canAddMore && count > 0
    const centered = disabled || count === 0

    return (
        <div className={cn(disabled && 'opacity-50')}>
            <div className="mb-1 text-xs font-semibold uppercase text-tertiary">{title}</div>
            <div
                ref={setNodeRef}
                className={cn(
                    'flex min-h-12 flex-col gap-1 rounded border border-dashed p-1 transition-colors',
                    centered && 'items-center justify-center text-center',
                    isOver && !disabled && !isFull && 'border-accent bg-accent-highlight-secondary',
                    isOver && isFull && 'border-warning bg-warning-highlight'
                )}
                data-attr={`sql-builder-well-${well}`}
            >
                {disabled ? (
                    <span className="px-2 text-xs text-tertiary">{disabledReason}</span>
                ) : count === 0 ? (
                    <span className="px-2 text-xs text-tertiary">{isOver ? 'Drop to add' : emptyHint}</span>
                ) : (
                    <>
                        {children}
                        {isFull ? (
                            isOver ? (
                                <span className="px-2 py-0.5 text-xs text-warning">Drop to replace</span>
                            ) : null
                        ) : (
                            <span className="rounded border border-dashed border-transparent px-2 py-0.5 text-xs text-tertiary">
                                {isOver ? 'Drop to add' : 'Drop another field'}
                            </span>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}

export function Wells({ tabId }: { tabId: string }): JSX.Element {
    const { rows, columnDims, measures, filterItems, builderDisplay } = useValues(insightBuilderLogic({ tabId }))

    const wellDisabled = (well: BuilderWell): { disabled: boolean; disabledReason?: string } =>
        isWellEnabled(well, builderDisplay)
            ? { disabled: false }
            : { disabled: true, disabledReason: `Not used by this chart type` }

    // The chart's capability caps each well; below the cap we hint that more fields fit
    const capability = getChartCapability(builderDisplay)
    const canAddMore = (well: 'rows' | 'columns' | 'values', count: number): boolean => {
        const max = capability?.[well].max
        return max === undefined ? true : max === null || count < max
    }

    return (
        <div className="flex flex-col gap-3">
            <Well
                well="rows"
                title="Rows"
                emptyHint="Drop a field to group by"
                count={rows.length}
                canAddMore={canAddMore('rows', rows.length)}
                {...wellDisabled('rows')}
            >
                <SortableContext
                    items={rows.map((_, index) => pillId('rows', index))}
                    strategy={verticalListSortingStrategy}
                >
                    {rows.map((dimension, index) => (
                        <DimensionPill
                            key={`${dimension.column}-${index}`}
                            tabId={tabId}
                            well="rows"
                            index={index}
                            dimension={dimension}
                        />
                    ))}
                </SortableContext>
            </Well>
            <Well
                well="columns"
                title="Columns"
                emptyHint="Drop a field to split series"
                count={columnDims.length}
                canAddMore={canAddMore('columns', columnDims.length)}
                {...wellDisabled('columns')}
            >
                <SortableContext
                    items={columnDims.map((_, index) => pillId('columns', index))}
                    strategy={verticalListSortingStrategy}
                >
                    {columnDims.map((dimension, index) => (
                        <DimensionPill
                            key={`${dimension.column}-${index}`}
                            tabId={tabId}
                            well="columns"
                            index={index}
                            dimension={dimension}
                        />
                    ))}
                </SortableContext>
            </Well>
            <Well
                well="values"
                title="Values"
                emptyHint="Drop a field to summarize"
                count={measures.length}
                canAddMore={canAddMore('values', measures.length)}
                {...wellDisabled('values')}
            >
                <SortableContext
                    items={measures.map((_, index) => pillId('values', index))}
                    strategy={verticalListSortingStrategy}
                >
                    {measures.map((measure, index) => (
                        <MeasurePill
                            key={`${measure.column}-${measure.aggregation}-${index}`}
                            tabId={tabId}
                            index={index}
                            measure={measure}
                        />
                    ))}
                </SortableContext>
            </Well>
            <Well
                well="filters"
                title="Filters"
                emptyHint="Drop a field to filter by"
                count={filterItems.length}
                canAddMore
            >
                <SortableContext
                    items={filterItems.map((_, index) => pillId('filters', index))}
                    strategy={verticalListSortingStrategy}
                >
                    {filterItems.map((filter, index) => (
                        <FilterPill key={`${filter.column}-${index}`} tabId={tabId} index={index} filter={filter} />
                    ))}
                </SortableContext>
            </Well>
        </div>
    )
}
