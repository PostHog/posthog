import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { cn } from 'lib/utils/css-classes'

import {
    AGGREGATION_LABELS,
    DATE_GRAIN_LABELS,
    DATE_GRAIN_OPTIONS,
    FILTER_OPERATORS,
    FILTER_OPERATOR_LABELS,
    NON_NUMERIC_AGGREGATIONS,
    NUMERIC_AGGREGATIONS,
    operatorNeedsValue,
} from '~/queries/nodes/DataVisualization/insightBuilder/builderLabels'
import { BuilderWell } from '~/queries/nodes/DataVisualization/insightBuilder/chartCapabilities'
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
    const { removeField, setDateGrain } = useActions(insightBuilderLogic({ tabId }))

    const field = baseFields.find((candidate) => candidate.name === dimension.column)
    const isDate = field?.isDate || !!dimension.dateGrain
    const isMissing = baseFields.length > 0 && !field

    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: pillId(well, index),
        data: { type: 'pill', well, index, item: dimension },
    })

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
                ) : null}
            </span>
        </LemonSnack>
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
            <span className="flex items-center gap-1">
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

    const isMissing = baseFields.length > 0 && !baseFields.some((candidate) => candidate.name === filter.column)
    const needsValue = operatorNeedsValue(filter.operator)

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
                    {FILTER_OPERATORS.map((operator) => (
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
                        <LemonInput
                            size="xsmall"
                            placeholder="value"
                            value={filter.value ?? ''}
                            onChange={(value) => updateFilter(index, { value })}
                            data-attr="sql-builder-filter-value"
                        />
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
}: {
    well: BuilderWell
    title: string
    emptyHint: string
    children: React.ReactNode
    count: number
}): JSX.Element {
    const { setNodeRef, isOver } = useDroppable({ id: `well:${well}`, data: { type: 'well', well } })

    return (
        <div>
            <div className="mb-1 text-xs font-semibold uppercase text-tertiary">{title}</div>
            <div
                ref={setNodeRef}
                className={cn(
                    'flex min-h-12 flex-col gap-1 rounded border border-dashed p-1 transition-colors',
                    isOver && 'border-accent bg-accent-highlight-secondary',
                    count === 0 && 'items-center justify-center'
                )}
                data-attr={`sql-builder-well-${well}`}
            >
                {count === 0 ? <span className="px-2 text-xs text-tertiary">{emptyHint}</span> : children}
            </div>
        </div>
    )
}

export function Wells({ tabId }: { tabId: string }): JSX.Element {
    const { rows, columnDims, measures, filterItems } = useValues(insightBuilderLogic({ tabId }))

    return (
        <div className="flex flex-col gap-3">
            <Well well="rows" title="Rows" emptyHint="Drop a field to group by" count={rows.length}>
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
            <Well well="columns" title="Columns" emptyHint="Drop a field to split series" count={columnDims.length}>
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
            <Well well="values" title="Values" emptyHint="Drop a field to summarize" count={measures.length}>
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
            <Well well="filters" title="Filters" emptyHint="Drop a field to filter by" count={filterItems.length}>
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
