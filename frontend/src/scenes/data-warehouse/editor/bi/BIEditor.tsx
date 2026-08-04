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
import { LemonButton, LemonCard, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { dayjs } from 'lib/dayjs'
import { Icon123, IconAreaChart, IconHeatmap, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import { ChartDisplayType } from '~/types'

import { editorSizingLogic } from '../editorSizingLogic'
import { queryDatabaseLogic } from '../sidebar/queryDatabaseLogic'
import { biEditorLogic } from './biEditorLogic'
import {
    BIAggregation,
    BI_FIELD_DRAG_MIME_TYPE,
    BIFilterOperator,
    BIShelf,
    BIField,
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
    { value: ChartDisplayType.TwoDimensionalHeatmap, label: '2D heatmap', icon: <IconHeatmap /> },
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

export function BIEditor({ tabId }: { tabId: string }): JSX.Element {
    const logic = biEditorLogic({ tabId })
    const { availableDataSources, config, databaseConnectionId, databaseLoading } = useValues(logic)
    const { setDatabaseTreeCollapsed } = useActions(editorSizingLogic)
    const { locateTable } = useActions(queryDatabaseLogic)
    const {
        addBlankFieldToShelf,
        addFieldToShelf,
        removeFieldFromShelf,
        resetConfig,
        setChartType,
        setDataSource,
        setFieldExpression,
        setFilterCustomExpression,
        setFilterOperator,
        setFilterValue,
        setValueAggregation,
        setValueCustomExpression,
    } = useActions(logic)

    return (
        <div className="flex h-[42%] min-h-72 shrink-0 flex-col gap-3 overflow-auto border-b bg-primary p-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div className="flex min-w-0 flex-col gap-1">
                    <div className="flex items-center gap-1">
                        <LemonLabel>Data source</LemonLabel>
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
                        <LemonSelect
                            value={config.source?.table}
                            options={availableDataSources.map((source) => ({
                                value: source.table,
                                label: source.table,
                            }))}
                            onSelect={(table) =>
                                setDataSource({ table, connectionId: databaseConnectionId ?? undefined })
                            }
                            icon={<IconDatabase />}
                            loading={databaseLoading}
                            disabledReason={
                                !databaseLoading && availableDataSources.length === 0
                                    ? 'No tables available for this connection'
                                    : undefined
                            }
                            placeholder="Select a table"
                            size="small"
                            className="min-w-64 max-w-120"
                            truncateText={{ maxWidthClass: 'max-w-96' }}
                            dropdownMaxContentWidth
                            data-attr="bi-editor-data-source"
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={resetConfig}
                            disabledReason={!config.source ? 'No BI setup to clear' : undefined}
                        >
                            Clear
                        </LemonButton>
                    </div>
                    {config.source ? (
                        <span className="text-xs text-secondary">
                            Fields are limited to this table and its related folders.
                        </span>
                    ) : null}
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

            <div className="grid min-h-0 grid-cols-1 gap-3 lg:grid-cols-2">
                <Shelf
                    shelf="rows"
                    title="Rows"
                    description="Group results by these fields"
                    icon={<IconTableChart />}
                    itemCount={config.rows.length}
                    onDropField={addFieldToShelf}
                    onAddField={() => addBlankFieldToShelf('rows')}
                    addFieldDisabledReason={!config.source ? 'Select a data source first' : undefined}
                >
                    {config.rows.map((field, index) => (
                        <FieldExpressionEditor
                            key={field.id}
                            field={field}
                            onChange={(expression) => setFieldExpression('rows', index, expression)}
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
                    onDropField={addFieldToShelf}
                    onAddField={() => addBlankFieldToShelf('columns')}
                    addFieldDisabledReason={!config.source ? 'Select a data source first' : undefined}
                >
                    {config.columns.map((field, index) => (
                        <FieldExpressionEditor
                            key={field.id}
                            field={field}
                            onChange={(expression) => setFieldExpression('columns', index, expression)}
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
                    onDropField={addFieldToShelf}
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
                                onChange={(expression) => setFieldExpression('values', index, expression)}
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
                    onDropField={addFieldToShelf}
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
                                    onChange={(expression) => setFieldExpression('filters', index, expression)}
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
        </div>
    )
}

function FieldExpressionEditor({
    field,
    onChange,
    onRemove,
}: {
    field: BIField
    onChange: (expression: string) => void
    onRemove: () => void
}): JSX.Element {
    return (
        <div className="flex w-full min-w-0 items-center gap-2 rounded">
            <ExpressionEditorButton
                value={field.expression}
                field={field}
                label="Edit field expression"
                emptyLabel="Select field"
                onChange={onChange}
            />
            <RemoveFieldButton field={field} onClick={onRemove} />
        </div>
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
    onChange,
}: {
    value: string
    field: BIField
    label: string
    emptyLabel?: string
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
    children,
    onDropField,
    onAddField,
    addFieldDisabledReason,
}: {
    shelf: BIShelf
    title: string
    description: string
    icon: ReactNode
    itemCount: number
    children: ReactNode
    onDropField: (field: NonNullable<ReturnType<typeof parseBIField>>, shelf: BIShelf) => void
    onAddField: () => void
    addFieldDisabledReason?: string
}): JSX.Element {
    const handleDrop = (event: DragEvent<HTMLDivElement>): void => {
        event.preventDefault()
        const field = parseBIField(event.dataTransfer.getData(BI_FIELD_DRAG_MIME_TYPE))
        if (field) {
            onDropField(field, shelf)
        }
    }

    return (
        <LemonCard
            hoverEffect={false}
            className="flex min-h-28 max-h-64 flex-col gap-2 overflow-hidden border-dashed p-3"
        >
            <div
                className="flex min-h-0 flex-1 flex-col gap-2"
                data-attr={`bi-editor-${shelf}-shelf`}
                onDragOver={(event) => {
                    event.preventDefault()
                    event.dataTransfer.dropEffect = 'copy'
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
