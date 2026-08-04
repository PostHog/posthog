import { useActions, useValues } from 'kea'
import type { DragEvent, ReactNode } from 'react'

import { IconCalculator, IconDatabase, IconFilter } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonLabel, LemonSelect, LemonSnack } from '@posthog/lemon-ui'

import { IconTableChart } from 'lib/lemon-ui/icons'

import { ChartDisplayType } from '~/types'

import { biEditorLogic } from './biEditorLogic'
import {
    BIAggregation,
    BI_FIELD_DRAG_MIME_TYPE,
    BIFilterOperator,
    BIShelf,
    isNumericBIField,
    parseBIField,
} from './biEditorTypes'

const CHART_TYPE_OPTIONS = [
    { value: ChartDisplayType.Auto, label: 'Auto' },
    { value: ChartDisplayType.ActionsTable, label: 'Table' },
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line chart' },
    { value: ChartDisplayType.ActionsBar, label: 'Bar chart' },
    { value: ChartDisplayType.ActionsStackedBar, label: 'Stacked bar chart' },
    { value: ChartDisplayType.ActionsAreaGraph, label: 'Area chart' },
    { value: ChartDisplayType.ActionsPie, label: 'Pie chart' },
    { value: ChartDisplayType.TwoDimensionalHeatmap, label: '2d heatmap' },
    { value: ChartDisplayType.BoldNumber, label: 'Big number' },
]

const AGGREGATION_OPTIONS: { value: BIAggregation; label: string }[] = [
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
    { value: 'is_set', label: 'Is set' },
    { value: 'is_not_set', label: 'Is not set' },
]

export function BIEditor({ tabId }: { tabId: string }): JSX.Element {
    const logic = biEditorLogic({ tabId })
    const { config } = useValues(logic)
    const {
        addFieldToShelf,
        removeFieldFromShelf,
        resetConfig,
        setChartType,
        setFilterOperator,
        setFilterValue,
        setValueAggregation,
    } = useActions(logic)

    return (
        <div className="flex h-[42%] min-h-72 shrink-0 flex-col gap-3 overflow-auto border-b bg-primary p-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div className="flex min-w-0 flex-col gap-1">
                    <LemonLabel>Data source</LemonLabel>
                    <div className="flex min-h-8 items-center gap-2">
                        <IconDatabase className="text-tertiary" />
                        <span className="truncate font-medium">
                            {config.source?.table ?? 'Drag a field from the sidebar'}
                        </span>
                    </div>
                    {config.source ? (
                        <span className="text-xs text-secondary">
                            Fields are limited to this table and its related folders.
                        </span>
                    ) : null}
                </div>
                <div className="flex items-end gap-2">
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Chart type</LemonLabel>
                        <LemonSelect
                            value={config.chartType}
                            options={CHART_TYPE_OPTIONS}
                            onChange={setChartType}
                            size="small"
                            dropdownMatchSelectWidth={false}
                            data-attr="bi-editor-chart-type"
                        />
                    </div>
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

            <div className="grid min-h-0 grid-cols-1 gap-3 lg:grid-cols-2">
                <Shelf
                    shelf="rows"
                    title="Rows"
                    description="Group results by these fields"
                    icon={<IconTableChart />}
                    onDropField={addFieldToShelf}
                >
                    {config.rows.map((field, index) => (
                        <LemonSnack key={field.id} onClose={() => removeFieldFromShelf('rows', index)}>
                            {field.name}
                        </LemonSnack>
                    ))}
                </Shelf>

                <Shelf
                    shelf="columns"
                    title="Columns"
                    description="Add a second grouping for charts that use one"
                    icon={<IconTableChart />}
                    onDropField={addFieldToShelf}
                >
                    {config.columns.map((field, index) => (
                        <LemonSnack key={field.id} onClose={() => removeFieldFromShelf('columns', index)}>
                            {field.name}
                        </LemonSnack>
                    ))}
                </Shelf>

                <Shelf
                    shelf="values"
                    title="Values"
                    description="Calculate the values shown in the chart"
                    icon={<IconCalculator />}
                    onDropField={addFieldToShelf}
                >
                    {config.values.map((value, index) => (
                        <div key={`${value.field.id}-${index}`} className="flex min-w-0 items-center gap-2">
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
                            <LemonSnack onClose={() => removeFieldFromShelf('values', index)}>
                                {value.field.name}
                            </LemonSnack>
                        </div>
                    ))}
                </Shelf>

                <Shelf
                    shelf="filters"
                    title="Filters"
                    description="Limit which rows are included"
                    icon={<IconFilter />}
                    onDropField={addFieldToShelf}
                >
                    {config.filters.map((filter, index) => {
                        const filterNeedsValue = filter.operator !== 'is_set' && filter.operator !== 'is_not_set'
                        return (
                            <div key={filter.field.id} className="flex min-w-0 flex-wrap items-center gap-2">
                                <LemonSnack onClose={() => removeFieldFromShelf('filters', index)}>
                                    {filter.field.name}
                                </LemonSnack>
                                <LemonSelect
                                    value={filter.operator}
                                    options={FILTER_OPERATOR_OPTIONS}
                                    onChange={(operator) => setFilterOperator(index, operator)}
                                    size="xsmall"
                                    dropdownMatchSelectWidth={false}
                                />
                                {filterNeedsValue ? (
                                    <LemonInput
                                        value={filter.value}
                                        onChange={(value) => setFilterValue(index, value)}
                                        placeholder="Value"
                                        size="small"
                                        className="min-w-32 flex-1"
                                    />
                                ) : null}
                            </div>
                        )
                    })}
                </Shelf>
            </div>
        </div>
    )
}

function Shelf({
    shelf,
    title,
    description,
    icon,
    children,
    onDropField,
}: {
    shelf: BIShelf
    title: string
    description: string
    icon: ReactNode
    children: ReactNode
    onDropField: (field: NonNullable<ReturnType<typeof parseBIField>>, shelf: BIShelf) => void
}): JSX.Element {
    const handleDrop = (event: DragEvent<HTMLDivElement>): void => {
        event.preventDefault()
        const field = parseBIField(event.dataTransfer.getData(BI_FIELD_DRAG_MIME_TYPE))
        if (field) {
            onDropField(field, shelf)
        }
    }

    return (
        <LemonCard hoverEffect={false} className="flex min-h-28 flex-col gap-2 border-dashed p-3">
            <div
                className="flex min-h-full flex-1 flex-col gap-2"
                data-attr={`bi-editor-${shelf}-shelf`}
                onDragOver={(event) => {
                    event.preventDefault()
                    event.dataTransfer.dropEffect = 'copy'
                }}
                onDrop={handleDrop}
            >
                <div className="flex items-center gap-2 font-medium">
                    <span className="text-tertiary">{icon}</span>
                    {title}
                </div>
                <span className="text-xs text-secondary">{description}</span>
                <div className="flex flex-1 flex-wrap content-start items-start gap-2">{children}</div>
            </div>
        </LemonCard>
    )
}
