import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { forwardRef, useRef, useState } from 'react'

import { IconChevronDown, IconGear, IconX } from '@posthog/icons'
import { LemonDialog, LemonTabs, Popover } from '@posthog/lemon-ui'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { cn } from 'lib/utils/css-classes'

import { YSeriesDisplayTab, YSeriesFormattingTab } from '~/queries/nodes/DataVisualization/Components/SeriesTab'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import {
    AGGREGATION_LABELS,
    DATE_GRAIN_LABELS,
    FILTER_OPERATOR_LABELS,
    NON_NUMERIC_AGGREGATIONS,
    NUMERIC_AGGREGATIONS,
    dateGrainOptionsForField,
    filterOperatorsForField,
    operatorNeedsValue,
} from '~/queries/nodes/DataVisualization/insightBuilder/builderLabels'
import {
    BuilderWell,
    getChartCapability,
    isWellEnabled,
    wellLabel,
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

/**
 * Neutral chip shell shared by all well pills: name + controls on a plain surface with a grip
 * cursor and a remove button. Drag attributes/listeners spread onto the root.
 */
interface FieldPillProps extends React.HTMLAttributes<HTMLDivElement> {
    onRemove: () => void
    isDragging?: boolean
    isMissing?: boolean
}

const FieldPill = forwardRef<HTMLDivElement, FieldPillProps>(function FieldPill(
    { onRemove, isDragging, isMissing, className, children, ...rest },
    ref
): JSX.Element {
    return (
        <div
            ref={ref}
            {...rest}
            className={cn(
                'flex w-full cursor-grab items-center gap-1 rounded border bg-surface-primary px-1.5 py-1 text-xs',
                isDragging && 'opacity-50',
                isMissing && 'border-danger',
                className
            )}
            data-attr="sql-builder-well-pill"
        >
            {children}
            <button
                type="button"
                className="inline-flex shrink-0 cursor-pointer items-center rounded p-0.5 text-secondary hover:bg-surface-secondary hover:text-primary"
                aria-label="Remove field"
                // Bubble phase: remove without engaging the pill's drag listeners
                onPointerDown={(e) => e.stopPropagation()}
                onClick={onRemove}
            >
                <IconX className="size-3" />
            </button>
        </div>
    )
})

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
        <FieldPill
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            onRemove={() => removeField(well, index)}
            isDragging={isDragging}
            isMissing={isMissing}
            title={isMissing ? `"${dimension.column}" is not in the base query results anymore` : undefined}
            style={{ transform: CSS.Transform.toString(transform), transition }}
        >
            <span className="flex min-w-0 flex-1 items-center gap-1">
                <span className="truncate">{dimension.column}</span>
                {isDate ? (
                    // Same affordance as the aggregation chip on value pills: the current choice
                    // is the dropdown's label
                    <PillMenu label={dimension.dateGrain ? DATE_GRAIN_LABELS[dimension.dateGrain] : 'Exact'}>
                        {dateGrainOptionsForField(field).map((grain) => (
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
        </FieldPill>
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
    const buttonRef = useRef<HTMLButtonElement>(null)

    const series = yData[index]
    if (!series) {
        return null
    }
    const seriesLogicProps = { series, seriesIndex: index, dataVisualizationProps }

    return (
        <Popover
            visible={open}
            // Presses on the gear must be the button's business alone. Popover's dismiss treats
            // them as "outside" (it only registers the child as a position reference, so
            // floating-ui has no DOM reference to recognize as inside) — without this guard a
            // click meant to close the popover dismisses it here and the button's toggle instantly
            // reopens it: the popover appears twice instead of closing. Guard pointer presses
            // only: Escape also arrives here (as a keydown targeting the focused gear) and must
            // still dismiss.
            onClickOutside={(event) => {
                if (
                    event instanceof MouseEvent &&
                    event.target instanceof Node &&
                    buttonRef.current?.contains(event.target)
                ) {
                    return
                }
                setOpen(false)
            }}
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
                ref={buttonRef}
                type="button"
                className="inline-flex shrink-0 cursor-pointer items-center rounded p-0.5 text-secondary hover:bg-surface-secondary"
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
        <FieldPill
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            onRemove={() => removeField('values', index)}
            isDragging={isDragging}
            isMissing={isMissing}
            title={isMissing ? `"${measure.column}" is not in the base query results anymore` : undefined}
            style={{ transform: CSS.Transform.toString(transform), transition }}
        >
            <span className="flex min-w-0 flex-1 items-center gap-1">
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
            <FieldSettingsButton index={index} />
        </FieldPill>
    )
}

/**
 * Filter value input that commits on blur/Enter rather than per keystroke — every commit
 * recompiles the query and (once the filter is complete) runs it, so mid-typing values like
 * "purch" must never reach the logic.
 */
function FilterValueInput({
    value,
    numeric,
    placeholder,
    onCommit,
}: {
    value: string
    numeric: boolean
    placeholder: string
    onCommit: (value: string) => void
}): JSX.Element {
    const [draft, setDraft] = useState<string | null>(null)
    const shown = draft ?? value
    const commit = (): void => {
        if (draft !== null && draft !== value) {
            onCommit(draft)
        }
        setDraft(null)
    }

    return numeric ? (
        <LemonInput
            size="xsmall"
            type="number"
            placeholder={placeholder}
            value={shown !== '' ? Number(shown) : undefined}
            onChange={(next) => setDraft(next != null ? String(next) : '')}
            onBlur={commit}
            onPressEnter={commit}
            data-attr="sql-builder-filter-value"
        />
    ) : (
        <LemonInput
            size="xsmall"
            placeholder={placeholder}
            value={shown}
            onChange={setDraft}
            onBlur={commit}
            onPressEnter={commit}
            data-attr="sql-builder-filter-value"
        />
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
        <FieldPill
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            onRemove={() => removeField('filters', index)}
            isDragging={isDragging}
            isMissing={isMissing}
            title={isMissing ? `"${filter.column}" is not in the base query results anymore` : undefined}
            style={{ transform: CSS.Transform.toString(transform), transition }}
        >
            <span className="flex min-w-0 flex-1 items-center gap-1">
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
                        <FilterValueInput
                            numeric={isNumericValue}
                            placeholder={valuePlaceholder}
                            value={filter.value ?? ''}
                            onCommit={(value) => updateFilter(index, { value })}
                        />
                    </span>
                ) : null}
            </span>
        </FieldPill>
    )
}

function Well({
    well,
    title,
    emptyHint,
    children,
    count,
    canAddMore,
}: {
    well: BuilderWell
    title: string
    emptyHint: string
    children: React.ReactNode
    count: number
    /** The current chart accepts more fields in this well — show a "drop another" hint */
    canAddMore?: boolean
}): JSX.Element {
    const { setNodeRef, isOver } = useDroppable({
        id: `well:${well}`,
        data: { type: 'well', well },
    })

    // A drop into a full well (no remaining capacity) replaces the existing field rather than adding
    const isFull = !canAddMore && count > 0
    const centered = count === 0

    return (
        <div>
            <div className="mb-1 text-xs font-semibold uppercase text-tertiary">{title}</div>
            <div
                ref={setNodeRef}
                className={cn(
                    'flex flex-col gap-1 rounded border border-dashed p-1 transition-colors',
                    // Empty wells keep a visible drop target sized like a well holding one pill —
                    // noticeably taller reads as a big empty box rather than a slot to fill
                    centered && 'min-h-9 items-center justify-center text-center',
                    isOver && !isFull && 'border-accent bg-accent-highlight-secondary',
                    isOver && isFull && 'border-warning bg-warning-highlight'
                )}
                data-attr={`sql-builder-well-${well}`}
            >
                {count === 0 ? (
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

// Wells speak the current chart's language, so drop hints are keyed by the well's label
const WELL_EMPTY_HINTS: Record<string, string> = {
    'X-axis': 'Drop a field for the x-axis',
    Breakdown: 'Drop a field to split the series',
    Slices: 'Drop a field for the slices',
    Rows: 'Drop a field for the y-axis',
    Columns: 'Drop a field to group by',
    Values: 'Drop a field to summarize',
    Value: 'Drop a field to summarize',
    Filters: 'Drop a field to filter by',
}

/**
 * Fields parked in wells the current chart doesn't use. They still compile to nothing (see
 * effectiveWells) but are kept so switching charts restores them — hiding them entirely would
 * leave config the user can't see or remove.
 */
function UnusedFields({ tabId }: { tabId: string }): JSX.Element | null {
    const { rows, columnDims, builderDisplay } = useValues(insightBuilderLogic({ tabId }))

    const parked = [
        ...(!isWellEnabled('rows', builderDisplay)
            ? rows.map((dimension, index) => ({ well: 'rows' as const, dimension, index }))
            : []),
        ...(!isWellEnabled('columns', builderDisplay)
            ? columnDims.map((dimension, index) => ({ well: 'columns' as const, dimension, index }))
            : []),
    ]
    if (parked.length === 0) {
        return null
    }

    const chartLabel = getChartCapability(builderDisplay)?.label ?? 'this chart'
    return (
        <div className="opacity-60" data-attr="sql-builder-unused-fields">
            <div className="mb-1 text-xs font-semibold uppercase text-tertiary">Unused fields</div>
            <div className="flex flex-col gap-1 rounded border border-dashed p-1">
                <SortableContext
                    items={parked.map(({ well, index }) => pillId(well, index))}
                    strategy={verticalListSortingStrategy}
                >
                    {parked.map(({ well, dimension, index }) => (
                        <DimensionPill
                            key={`${well}-${dimension.column}-${index}`}
                            tabId={tabId}
                            well={well}
                            index={index}
                            dimension={dimension}
                        />
                    ))}
                </SortableContext>
                <span className="px-2 py-0.5 text-xs text-tertiary">
                    Not used by {chartLabel} — kept for other chart types
                </span>
            </div>
        </div>
    )
}

export function Wells({ tabId }: { tabId: string }): JSX.Element {
    const { rows, columnDims, measures, filterItems, builderDisplay } = useValues(insightBuilderLogic({ tabId }))

    // The chart's capability caps each well; below the cap we hint that more fields fit
    const capability = getChartCapability(builderDisplay)
    const canAddMore = (well: 'rows' | 'columns' | 'values', count: number): boolean => {
        const max = capability?.[well].max
        return max === undefined ? true : max === null || count < max
    }
    const labelFor = (well: BuilderWell): string => wellLabel(well, builderDisplay)
    const hintFor = (well: BuilderWell): string => WELL_EMPTY_HINTS[labelFor(well)] ?? 'Drop a field'

    return (
        <div className="flex flex-col gap-3">
            {isWellEnabled('rows', builderDisplay) ? (
                <Well
                    well="rows"
                    title={labelFor('rows')}
                    emptyHint={hintFor('rows')}
                    count={rows.length}
                    canAddMore={canAddMore('rows', rows.length)}
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
            ) : null}
            {isWellEnabled('columns', builderDisplay) ? (
                <Well
                    well="columns"
                    title={labelFor('columns')}
                    emptyHint={hintFor('columns')}
                    count={columnDims.length}
                    canAddMore={canAddMore('columns', columnDims.length)}
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
            ) : null}
            <Well
                well="values"
                title={labelFor('values')}
                emptyHint={hintFor('values')}
                count={measures.length}
                canAddMore={canAddMore('values', measures.length)}
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
                emptyHint={WELL_EMPTY_HINTS.Filters}
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
            <UnusedFields tabId={tabId} />
        </div>
    )
}
