import { useActions, useValues } from 'kea'
import type { DragEvent, ReactNode } from 'react'

import {
    IconCalculator,
    IconDatabase,
    IconFilter,
    IconGraph,
    IconLifecycle,
    IconMagicWand,
    IconPencil,
    IconPieChart,
    IconPlus,
    IconTrends,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonLabel, LemonSearchableSelect, LemonSelect } from '@posthog/lemon-ui'

import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { dayjs } from 'lib/dayjs'
import { Icon123, IconAreaChart, IconHeatmap, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { cn } from 'lib/utils/css-classes'

import { ChartDisplayType } from '~/types'

import { editorSizingLogic } from '../editorSizingLogic'
import { queryDatabaseLogic } from '../sidebar/queryDatabaseLogic'
import { biEditorLogic } from './biEditorLogic'
import {
    BIAggregation,
    BIDateBucket,
    BI_FIELD_DRAG_MIME_TYPE,
    BI_QUERY_LIMITS,
    BIFilterOperator,
    BIShelf,
    BIField,
    BISortDirection,
    PIVOT_TABLE_QUERY_LIMIT,
    getBIDataSourceKey,
    isDateTimeBIField,
    isNumericBIField,
    parseBIField,
} from './biEditorTypes'

const CHART_TYPE_OPTIONS: { value: ChartDisplayType; label: string; icon: JSX.Element }[] = [
    { value: ChartDisplayType.Auto, label: 'Auto', icon: <IconMagicWand /> },
    { value: ChartDisplayType.ActionsTable, label: 'Table', icon: <IconTableChart /> },
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line chart', icon: <IconTrends /> },
    { value: ChartDisplayType.ActionsBar, label: 'Bar chart', icon: <IconGraph /> },
    { value: ChartDisplayType.ActionsStackedBar, label: 'Stacked bar chart', icon: <IconLifecycle /> },
    { value: ChartDisplayType.ActionsAreaGraph, label: 'Area chart', icon: <IconAreaChart /> },
    { value: ChartDisplayType.ActionsPie, label: 'Pie chart', icon: <IconPieChart /> },
    { value: ChartDisplayType.TwoDimensionalHeatmap, label: 'Pivot table', icon: <IconHeatmap /> },
    { value: ChartDisplayType.BoldNumber, label: 'Big number', icon: <Icon123 /> },
]

const AGGREGATION_OPTIONS: { value: BIAggregation; label: string }[] = [
    { value: 'custom', label: 'SQL expression' },
    { value: 'count', label: 'Count' },
    { value: 'count_distinct', label: 'Count distinct' },
    { value: 'sum', label: 'Sum' },
    { value: 'average', label: 'Average' },
    { value: 'minimum', label: 'Minimum' },
    { value: 'maximum', label: 'Maximum' },
]

const FILTER_OPERATOR_OPTIONS: { value: BIFilterOperator; label: string }[] = [
    { value: 'equals', label: 'Equals' },
    { value: 'not_equals', label: 'Does not equal' },
    { value: 'contains', label: 'Contains' },
    { value: 'greater_than', label: 'Greater than' },
    { value: 'less_than', label: 'Less than' },
    { value: 'last_7_days', label: 'Last 7 days' },
    { value: 'is_set', label: 'Is set' },
    { value: 'is_not_set', label: 'Is not set' },
    { value: 'custom', label: 'SQL condition' },
]

const DATE_BUCKET_OPTIONS: { value: BIDateBucket | null; label: string }[] = [
    { value: null, label: 'Exact' },
    { value: 'minute', label: 'Minute' },
    { value: 'hour', label: 'Hour' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
    { value: 'quarter', label: 'Quarter' },
    { value: 'year', label: 'Year' },
]

const LIMIT_OPTIONS = BI_QUERY_LIMITS.map((limit) => ({
    value: limit,
    label: limit === 1000 ? '1k' : limit === 10000 ? '10k' : limit === 50000 ? '50k' : String(limit),
}))

const SORT_DIRECTION_OPTIONS: { value: BISortDirection; label: string }[] = [
    { value: 'desc', label: 'Descending' },
    { value: 'asc', label: 'Ascending' },
]

export function BIEditor({ tabId }: { tabId: string }): JSX.Element {
    const logic = biEditorLogic({ tabId })
    const { activeDropShelf, activeExpressionEditorId, availableDataSources, config, databaseLoading, sortOptions } =
        useValues(logic)
    const { biEditorHeight, biEditorResizerProps } = useValues(editorSizingLogic)
    const { setDatabaseTreeCollapsed } = useActions(editorSizingLogic)
    const { locateTable } = useActions(queryDatabaseLogic)
    const {
        addBlankFieldToShelf,
        addFieldToShelf,
        clearActiveDropShelf,
        removeFieldFromShelf,
        resetConfig,
        setActiveDropShelf,
        setActiveExpressionEditorId,
        setChartType,
        setDataSource,
        setFieldDateBucket,
        setFieldExpression,
        setFilterCustomExpression,
        setFilterOperator,
        setFilterValue,
        setLimit,
        setSort,
        setValueAggregation,
        setValueCustomExpression,
    } = useActions(logic)
    const limitOptions =
        config.chartType === ChartDisplayType.TwoDimensionalHeatmap
            ? LIMIT_OPTIONS.filter(({ value }) => value <= PIVOT_TABLE_QUERY_LIMIT)
            : LIMIT_OPTIONS

    return (
        <div
            className="relative flex min-h-44 shrink-0 flex-col gap-3 overflow-hidden border-b bg-primary p-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: `${biEditorHeight}px`, maxHeight: 'calc(100% - 10rem)' }}
            ref={biEditorResizerProps.containerRef}
        >
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div className="flex min-w-0 flex-col gap-1">
                    <div className="flex items-center gap-1">
                        <LemonLabel info="Fields are limited to this table and its related folders.">
                            Data source
                        </LemonLabel>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            disabledReason={!config.source ? 'Select a data source first' : undefined}
                            onClick={() => {
                                if (config.source) {
                                    setDatabaseTreeCollapsed(false)
                                    locateTable(config.source.table)
                                }
                            }}
                        >
                            Locate
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonSearchableSelect
                            value={config.source ? getBIDataSourceKey(config.source) : undefined}
                            options={availableDataSources.map((source) => ({
                                value: getBIDataSourceKey(source),
                                label: source.table,
                            }))}
                            onSelect={(sourceKey) => {
                                const source = availableDataSources.find(
                                    (candidate) => getBIDataSourceKey(candidate) === sourceKey
                                )
                                if (source) {
                                    setDataSource(source)
                                }
                            }}
                            icon={<IconDatabase />}
                            loading={databaseLoading}
                            disabledReason={
                                !databaseLoading && availableDataSources.length === 0
                                    ? 'No tables available for this connection'
                                    : undefined
                            }
                            placeholder="Select a table"
                            searchPlaceholder="Search tables"
                            searchInputDataAttr="bi-editor-data-source-search"
                            noResultsMessage="No matching tables"
                            size="small"
                            className="min-w-64 max-w-120"
                            truncateText={{ maxWidthClass: 'max-w-96' }}
                            dropdownMaxContentWidth
                            data-attr="bi-editor-data-source"
                        />
                        <LemonSelect
                            value={config.limit}
                            options={limitOptions}
                            onChange={setLimit}
                            renderButtonContent={(option) => `Limit: ${option?.label ?? config.limit}`}
                            aria-label="Query row limit"
                            size="small"
                            dropdownMatchSelectWidth={false}
                            data-attr="bi-editor-query-limit"
                        />
                        <LemonSelect
                            value={config.sort?.key ?? null}
                            options={[
                                {
                                    value: null,
                                    label: 'Auto',
                                    tooltip:
                                        'Sorts by the newest date or the highest value first, so the top rows stay within the limit.',
                                },
                                ...sortOptions.map((option) => ({ value: option.key, label: option.label })),
                            ]}
                            onChange={(key) =>
                                setSort(key === null ? null : { key, direction: config.sort?.direction ?? 'desc' })
                            }
                            renderButtonContent={(option) => `Sort: ${option?.label ?? 'Auto'}`}
                            aria-label="Sort results by"
                            size="small"
                            dropdownMatchSelectWidth={false}
                            disabledReason={
                                sortOptions.length === 0 ? 'Add a field to rows or columns first' : undefined
                            }
                            data-attr="bi-editor-sort"
                        />
                        {config.sort ? (
                            <LemonSelect
                                value={config.sort.direction}
                                options={SORT_DIRECTION_OPTIONS}
                                onChange={(direction) => config.sort && setSort({ key: config.sort.key, direction })}
                                aria-label="Sort direction"
                                size="small"
                                dropdownMatchSelectWidth={false}
                                data-attr="bi-editor-sort-direction"
                            />
                        ) : null}
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={resetConfig}
                            disabledReason={!config.source ? 'No BI setup to clear' : undefined}
                        >
                            Clear
                        </LemonButton>
                    </div>
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Chart type</LemonLabel>
                    <div className="flex flex-wrap gap-1" role="group" aria-label="Chart type">
                        {CHART_TYPE_OPTIONS.map((option) => (
                            <LemonButton
                                key={option.value}
                                type={config.chartType === option.value ? 'primary' : 'secondary'}
                                active={config.chartType === option.value}
                                icon={option.icon}
                                size="small"
                                tooltip={option.label}
                                aria-label={option.label}
                                data-attr={`bi-editor-chart-type-${option.value}`}
                                onClick={() => setChartType(option.value)}
                            />
                        ))}
                    </div>
                </div>
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-auto lg:grid-cols-2">
                <Shelf
                    shelf="rows"
                    title="Rows"
                    description="Group results by these fields"
                    icon={<IconTableChart />}
                    itemCount={config.rows.length}
                    isActiveDropTarget={activeDropShelf === 'rows'}
                    onDropField={addFieldToShelf}
                    onActiveDropTargetChange={(active) =>
                        active ? setActiveDropShelf('rows') : clearActiveDropShelf('rows')
                    }
                    onAddField={() => addBlankFieldToShelf('rows')}
                    addFieldDisabledReason={!config.source ? 'Select a data source first' : undefined}
                >
                    {config.rows.map((field, index) => (
                        <FieldExpressionEditor
                            key={field.id}
                            field={field}
                            autoOpen={activeExpressionEditorId === field.id}
                            onAutoOpenClose={() => setActiveExpressionEditorId(null)}
                            onChange={(expression) => setFieldExpression('rows', index, expression)}
                            onDateBucketChange={(dateBucket) => setFieldDateBucket('rows', index, dateBucket)}
                            onRemove={() => removeFieldFromShelf('rows', index)}
                        />
                    ))}
                </Shelf>

                <Shelf
                    shelf="columns"
                    title="Columns"
                    description="Add a second grouping for charts that use one"
                    icon={<IconTableChart />}
                    itemCount={config.columns.length}
                    isActiveDropTarget={activeDropShelf === 'columns'}
                    onDropField={addFieldToShelf}
                    onActiveDropTargetChange={(active) =>
                        active ? setActiveDropShelf('columns') : clearActiveDropShelf('columns')
                    }
                    onAddField={() => addBlankFieldToShelf('columns')}
                    addFieldDisabledReason={!config.source ? 'Select a data source first' : undefined}
                >
                    {config.columns.map((field, index) => (
                        <FieldExpressionEditor
                            key={field.id}
                            field={field}
                            autoOpen={activeExpressionEditorId === field.id}
                            onAutoOpenClose={() => setActiveExpressionEditorId(null)}
                            onChange={(expression) => setFieldExpression('columns', index, expression)}
                            onDateBucketChange={(dateBucket) => setFieldDateBucket('columns', index, dateBucket)}
                            onRemove={() => removeFieldFromShelf('columns', index)}
                        />
                    ))}
                </Shelf>

                <Shelf
                    shelf="values"
                    title="Values"
                    description="Calculate the values shown in the chart"
                    icon={<IconCalculator />}
                    itemCount={config.values.length}
                    isActiveDropTarget={activeDropShelf === 'values'}
                    onDropField={addFieldToShelf}
                    onActiveDropTargetChange={(active) =>
                        active ? setActiveDropShelf('values') : clearActiveDropShelf('values')
                    }
                    onAddField={() => addBlankFieldToShelf('values')}
                    addFieldDisabledReason={!config.source ? 'Select a data source first' : undefined}
                >
                    {config.values.map((value, index) => (
                        <div
                            key={`${value.field.id}-${index}`}
                            className="flex w-full min-w-0 items-center gap-2 rounded"
                        >
                            <LemonSelect
                                value={value.aggregation}
                                options={AGGREGATION_OPTIONS.map((option) => ({
                                    ...option,
                                    disabledReason:
                                        !isNumericBIField(value.field) &&
                                        ['sum', 'average', 'minimum', 'maximum'].includes(option.value)
                                            ? 'This calculation requires a numeric field'
                                            : undefined,
                                }))}
                                onChange={(aggregation) => setValueAggregation(index, aggregation)}
                                size="xsmall"
                                dropdownMatchSelectWidth={false}
                            />
                            <ExpressionEditorButton
                                value={value.field.expression}
                                field={value.field}
                                label="Edit field expression"
                                emptyLabel="Select field"
                                visible={activeExpressionEditorId === value.field.id ? true : undefined}
                                onVisibilityChange={(visible) => {
                                    if (!visible) {
                                        setActiveExpressionEditorId(null)
                                    }
                                }}
                                onChange={(expression) => setFieldExpression('values', index, expression)}
                            />
                            <DateBucketSelect
                                field={value.field}
                                onChange={(dateBucket) => setFieldDateBucket('values', index, dateBucket)}
                            />
                            {value.aggregation === 'custom' ? (
                                <ExpressionEditorButton
                                    value={value.customExpression ?? ''}
                                    field={value.field}
                                    label={
                                        value.customExpression
                                            ? 'Edit aggregation SQL expression'
                                            : 'Add aggregation SQL expression'
                                    }
                                    emptyLabel="Add aggregation SQL expression"
                                    onChange={(customExpression) => setValueCustomExpression(index, customExpression)}
                                />
                            ) : null}
                            <RemoveFieldButton
                                field={value.field}
                                onClick={() => removeFieldFromShelf('values', index)}
                            />
                        </div>
                    ))}
                </Shelf>

                <Shelf
                    shelf="filters"
                    title="Filters"
                    description="Limit which rows are included"
                    icon={<IconFilter />}
                    itemCount={config.filters.length}
                    isActiveDropTarget={activeDropShelf === 'filters'}
                    onDropField={addFieldToShelf}
                    onActiveDropTargetChange={(active) =>
                        active ? setActiveDropShelf('filters') : clearActiveDropShelf('filters')
                    }
                    onAddField={() => addBlankFieldToShelf('filters')}
                    addFieldDisabledReason={!config.source ? 'Select a data source first' : undefined}
                >
                    {config.filters.map((filter, index) => {
                        const filterNeedsValue = !['last_7_days', 'is_set', 'is_not_set', 'custom'].includes(
                            filter.operator
                        )
                        return (
                            <div key={filter.field.id} className="flex w-full min-w-0 items-center gap-2 rounded">
                                <ExpressionEditorButton
                                    value={filter.field.expression}
                                    field={filter.field}
                                    label="Edit field expression"
                                    emptyLabel="Select field"
                                    visible={activeExpressionEditorId === filter.field.id ? true : undefined}
                                    onVisibilityChange={(visible) => {
                                        if (!visible) {
                                            setActiveExpressionEditorId(null)
                                        }
                                    }}
                                    onChange={(expression) => setFieldExpression('filters', index, expression)}
                                />
                                <DateBucketSelect
                                    field={filter.field}
                                    onChange={(dateBucket) => setFieldDateBucket('filters', index, dateBucket)}
                                />
                                <LemonSelect
                                    value={filter.operator}
                                    options={FILTER_OPERATOR_OPTIONS.map((option) => ({
                                        ...option,
                                        disabledReason:
                                            option.value === 'last_7_days' && !isDateTimeBIField(filter.field)
                                                ? 'Choose a date or date-time field'
                                                : undefined,
                                    }))}
                                    onChange={(operator) => setFilterOperator(index, operator)}
                                    size="xsmall"
                                    dropdownMatchSelectWidth={false}
                                />
                                {filter.operator === 'custom' ? (
                                    <ExpressionEditorButton
                                        value={filter.customExpression ?? ''}
                                        field={filter.field}
                                        label={
                                            filter.customExpression
                                                ? 'Edit filter SQL condition'
                                                : 'Add filter SQL condition'
                                        }
                                        emptyLabel="Add filter SQL condition"
                                        onChange={(customExpression) =>
                                            setFilterCustomExpression(index, customExpression)
                                        }
                                    />
                                ) : filterNeedsValue ? (
                                    isDateTimeBIField(filter.field) ? (
                                        <DateTimeFilterInput
                                            field={filter.field}
                                            value={filter.value}
                                            onChange={(value) => setFilterValue(index, value)}
                                        />
                                    ) : (
                                        <LemonInput
                                            value={filter.value}
                                            onChange={(value) => setFilterValue(index, value)}
                                            placeholder="Value"
                                            aria-label={`${filter.field.name} filter value`}
                                            size="small"
                                        />
                                    )
                                ) : null}
                                <RemoveFieldButton
                                    field={filter.field}
                                    onClick={() => removeFieldFromShelf('filters', index)}
                                />
                            </div>
                        )
                    })}
                </Shelf>
            </div>
            <Resizer {...biEditorResizerProps} />
        </div>
    )
}

function FieldExpressionEditor({
    field,
    autoOpen,
    onAutoOpenClose,
    onChange,
    onDateBucketChange,
    onRemove,
}: {
    field: BIField
    autoOpen: boolean
    onAutoOpenClose: () => void
    onChange: (expression: string) => void
    onDateBucketChange: (dateBucket: BIDateBucket | null) => void
    onRemove: () => void
}): JSX.Element {
    return (
        <div className="flex w-full min-w-0 items-center gap-2 rounded">
            <ExpressionEditorButton
                value={field.expression}
                field={field}
                label="Edit field expression"
                emptyLabel="Select field"
                visible={autoOpen ? true : undefined}
                onVisibilityChange={(visible) => {
                    if (!visible) {
                        onAutoOpenClose()
                    }
                }}
                onChange={onChange}
            />
            <DateBucketSelect field={field} onChange={onDateBucketChange} />
            <RemoveFieldButton field={field} onClick={onRemove} />
        </div>
    )
}

function DateBucketSelect({
    field,
    onChange,
}: {
    field: BIField
    onChange: (dateBucket: BIDateBucket | null) => void
}): JSX.Element | null {
    if (!isDateTimeBIField(field)) {
        return null
    }

    return (
        <LemonSelect
            value={field.dateBucket ?? null}
            options={DATE_BUCKET_OPTIONS}
            onChange={onChange}
            size="xsmall"
            dropdownMatchSelectWidth={false}
            data-attr="bi-editor-date-bucket"
        />
    )
}

function RemoveFieldButton({ field, onClick }: { field: BIField; onClick: () => void }): JSX.Element {
    const fieldName = field.name || 'field'

    return (
        <LemonButton
            icon={<IconX />}
            size="xsmall"
            type="tertiary"
            noPadding
            className="shrink-0"
            tooltip={`Remove ${fieldName}`}
            aria-label={`Remove ${fieldName}`}
            onClick={onClick}
        />
    )
}

function ExpressionEditorButton({
    value,
    field,
    label,
    emptyLabel,
    visible,
    onVisibilityChange,
    onChange,
}: {
    value: string
    field: BIField
    label: string
    emptyLabel?: string
    visible?: boolean
    onVisibilityChange?: (visible: boolean) => void
    onChange: (value: string) => void
}): JSX.Element {
    return (
        <HogQLDropdown
            hogQLValue={value}
            onHogQLValueChange={onChange}
            tableName={field.source.table}
            connectionId={field.source.connectionId}
            size="small"
            buttonIcon={<IconPencil />}
            buttonLabel={value ? <code className="truncate">{value}</code> : emptyLabel}
            buttonTooltip={label}
            buttonAriaLabel={`${label} for ${field.name || 'field'}`}
            visible={visible}
            onVisibilityChange={onVisibilityChange}
        />
    )
}

function DateTimeFilterInput({
    field,
    value,
    onChange,
}: {
    field: BIField
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const selectedDate = value && dayjs(value).isValid() ? dayjs(value) : null
    const includesTime = field.type === 'datetime'

    return (
        <LemonCalendarSelectInput
            value={selectedDate}
            onChange={(date) => onChange(date?.format(includesTime ? 'YYYY-MM-DD HH:mm:ss' : 'YYYY-MM-DD') ?? '')}
            granularity={includesTime ? 'minute' : 'day'}
            format={includesTime ? 'MMM D, YYYY HH:mm' : 'MMM D, YYYY'}
            use24HourFormat
            clearable
            placeholder={includesTime ? 'Select date and time' : 'Select date'}
            buttonProps={{ size: 'small', 'aria-label': `${field.name} filter date` }}
        />
    )
}

function Shelf({
    shelf,
    title,
    description,
    icon,
    itemCount,
    isActiveDropTarget,
    children,
    onDropField,
    onActiveDropTargetChange,
    onAddField,
    addFieldDisabledReason,
}: {
    shelf: BIShelf
    title: string
    description: string
    icon: ReactNode
    itemCount: number
    isActiveDropTarget: boolean
    children: ReactNode
    onDropField: (field: NonNullable<ReturnType<typeof parseBIField>>, shelf: BIShelf) => void
    onActiveDropTargetChange: (active: boolean) => void
    onAddField: () => void
    addFieldDisabledReason?: string
}): JSX.Element {
    const handleDrop = (event: DragEvent<HTMLDivElement>): void => {
        event.preventDefault()
        onActiveDropTargetChange(false)
        const field = parseBIField(event.dataTransfer.getData(BI_FIELD_DRAG_MIME_TYPE))
        if (field) {
            onDropField(field, shelf)
        }
    }

    return (
        <LemonCard
            hoverEffect={false}
            className={cn(
                'flex min-h-28 max-h-64 flex-col gap-2 overflow-hidden border-dashed p-3 transition-colors',
                isActiveDropTarget && 'border-accent bg-accent-highlight-secondary ring-2 ring-inset ring-accent'
            )}
        >
            <div
                className="flex min-h-0 flex-1 flex-col gap-2"
                data-attr={`bi-editor-${shelf}-shelf`}
                onDragEnter={(event) => {
                    if (Array.from(event.dataTransfer.types).includes(BI_FIELD_DRAG_MIME_TYPE)) {
                        onActiveDropTargetChange(true)
                    }
                }}
                onDragOver={(event) => {
                    if (Array.from(event.dataTransfer.types).includes(BI_FIELD_DRAG_MIME_TYPE)) {
                        event.preventDefault()
                        event.dataTransfer.dropEffect = 'copy'
                    }
                }}
                onDragLeave={(event) => {
                    const nextTarget = event.relatedTarget
                    if (!nextTarget || !event.currentTarget.contains(nextTarget as Node)) {
                        onActiveDropTargetChange(false)
                    }
                }}
                onDrop={handleDrop}
            >
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 font-medium">
                        <span className="text-tertiary">{icon}</span>
                        {title} ({itemCount})
                    </div>
                    <LemonButton
                        icon={<IconPlus />}
                        size="xsmall"
                        type="tertiary"
                        noPadding
                        tooltip="Add field"
                        aria-label={`Add field to ${title.toLowerCase()}`}
                        disabledReason={addFieldDisabledReason}
                        onClick={onAddField}
                        data-attr={`bi-editor-${shelf}-add-field`}
                    />
                </div>
                <span className="shrink-0 text-xs text-secondary">{description}</span>
                <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">{children}</div>
            </div>
        </LemonCard>
    )
}
