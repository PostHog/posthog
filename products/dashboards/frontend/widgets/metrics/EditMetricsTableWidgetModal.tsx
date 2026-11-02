import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect, type LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'

import { MetricNameFilter } from 'products/metrics/frontend/components/MetricNameFilter'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import {
    METRICS_TABLE_MAX_COLUMNS,
    type MetricsTableInterval,
    type MetricsTableOrderDirection,
    editMetricsTableWidgetModalLogic,
} from './editMetricsTableWidgetModalLogic'
import {
    METRICS_TABLE_DATE_RANGE_OPTIONS,
    type MetricsTableAggregation,
    type MetricsTableColumn,
} from './metricsTableWidgetConfigValidation'

type MetricsTableFilter = NonNullable<MetricsTableColumn['filters']>[number]
type MetricsTableFilterOp = NonNullable<MetricsTableFilter['op']>

const AGGREGATION_OPTIONS: LemonSelectOptions<MetricsTableAggregation> = [
    { value: 'rate', label: 'Rate per second (counter)' },
    { value: 'increase', label: 'Total increase (counter)' },
    { value: 'histogram_quantile', label: 'Percentile (histogram)' },
    { value: 'avg', label: 'Average' },
    { value: 'sum', label: 'Sum' },
    { value: 'min', label: 'Minimum' },
    { value: 'max', label: 'Maximum' },
]

const FILTER_OP_OPTIONS: LemonSelectOptions<MetricsTableFilterOp> = [
    { value: 'eq', label: '=' },
    { value: 'neq', label: '≠' },
    { value: 'regex', label: '=~' },
    { value: 'not_regex', label: '!~' },
]

const INTERVAL_OPTIONS: LemonSelectOptions<MetricsTableInterval | null> = [
    { value: null, label: 'Auto' },
    { value: 'minute', label: '1 minute' },
    { value: 'minute_5', label: '5 minutes' },
    { value: 'minute_15', label: '15 minutes' },
    { value: 'hour', label: '1 hour' },
    { value: 'day', label: '1 day' },
]

const ORDER_DIRECTION_OPTIONS: LemonSelectOptions<MetricsTableOrderDirection> = [
    { value: 'DESC', label: 'Highest first' },
    { value: 'ASC', label: 'Lowest first' },
]

/** The modal edits the first filter of a column. Filters after it, set through the API, stay as they are. */
function withFirstFilter(column: MetricsTableColumn, patch: Partial<MetricsTableFilter>): MetricsTableFilter[] {
    const [first, ...rest] = column.filters ?? []
    const next: MetricsTableFilter = { ...(first ?? { key: '', op: 'eq', value: '' }), ...patch }
    return next.key.trim() ? [next, ...rest] : rest
}

function ColumnEditor({ column, index }: { column: MetricsTableColumn; index: number }): JSX.Element {
    const { saving, columns } = useValues(editMetricsTableWidgetModalLogic)
    const { updateColumn, removeColumn } = useActions(editMetricsTableWidgetModalLogic)
    const filter = column.filters?.[0]

    return (
        <div className="flex flex-col gap-2 rounded border p-3" data-attr="metrics-table-widget-column">
            <div className="flex items-end gap-2">
                <LemonField.Pure label="Column name" className="w-32 shrink-0">
                    <LemonInput
                        value={column.label}
                        disabled={saving}
                        onChange={(label) => updateColumn(index, { label })}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Metric" className="flex-1 min-w-0">
                    <MetricNameFilter
                        value={column.metricName}
                        allowCustomName
                        disabled={saving}
                        onChange={(metricName) => updateColumn(index, { metricName })}
                    />
                </LemonField.Pure>
                <LemonButton
                    icon={<IconTrash />}
                    size="small"
                    status="danger"
                    disabledReason={columns.length === 1 ? 'The table needs at least one column' : undefined}
                    onClick={() => removeColumn(index)}
                    tooltip="Remove column"
                />
            </div>
            <div className="flex flex-wrap items-end gap-2">
                <LemonField.Pure label="Calculation" className="w-56">
                    <LemonSelect
                        value={column.aggregation}
                        options={AGGREGATION_OPTIONS}
                        disabled={saving}
                        onChange={(aggregation) => aggregation && updateColumn(index, { aggregation })}
                        fullWidth
                    />
                </LemonField.Pure>
                {column.aggregation === 'histogram_quantile' ? (
                    <LemonField.Pure label="Percentile" className="w-24">
                        <LemonInput
                            type="number"
                            min={1}
                            max={99}
                            value={Math.round((column.quantile ?? 0.95) * 100)}
                            disabled={saving}
                            onChange={(value) => updateColumn(index, { quantile: Number(value) / 100 })}
                        />
                    </LemonField.Pure>
                ) : null}
                <LemonField.Pure label="Only where label" className="flex-1 min-w-40">
                    <div className="flex gap-1">
                        <LemonInput
                            value={filter?.key ?? ''}
                            placeholder="status"
                            disabled={saving}
                            onChange={(key) => updateColumn(index, { filters: withFirstFilter(column, { key }) })}
                            fullWidth
                        />
                        <LemonSelect
                            value={filter?.op ?? 'eq'}
                            options={FILTER_OP_OPTIONS}
                            disabled={saving || !filter}
                            onChange={(op) => op && updateColumn(index, { filters: withFirstFilter(column, { op }) })}
                        />
                        <LemonInput
                            value={filter?.value ?? ''}
                            placeholder="5.."
                            disabled={saving || !filter}
                            onChange={(value) => updateColumn(index, { filters: withFirstFilter(column, { value }) })}
                            fullWidth
                        />
                    </div>
                </LemonField.Pure>
            </div>
        </div>
    )
}

function EditMetricsTableWidgetModalContents(): JSX.Element {
    const {
        tileName,
        tileDescription,
        defaultTitle,
        saving,
        onClose,
        saveDisabledReason,
        groupBy,
        columns,
        dateFrom,
        interval,
        limit,
        orderByColumn,
        orderDirection,
    } = useValues(editMetricsTableWidgetModalLogic)
    const {
        setTileName,
        setTileDescription,
        submit,
        setGroupBy,
        addColumn,
        setDateFrom,
        setInterval,
        setLimit,
        setOrderByColumn,
        setOrderDirection,
    } = useActions(editMetricsTableWidgetModalLogic)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Widget settings"
            description="Show one row for each value of a label, with a column for each metric."
            width={800}
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton type="secondary" onClick={onClose} disabled={saving}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        onClick={() => submit()}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <EditWidgetModalTileDetailsSection
                    tileName={tileName}
                    tileDescription={tileDescription}
                    defaultTitle={defaultTitle}
                    saving={saving}
                    setTileName={setTileName}
                    setTileDescription={setTileDescription}
                />
                <LemonDivider className="my-0" />
                <section className="flex flex-col gap-3">
                    <h5 className="text-sm font-semibold m-0">{getDashboardWidgetGroupLabel('metrics')}</h5>
                    <LemonField.Pure
                        label="One row for each value of"
                        help="A label on your metrics, such as http.route or service.name."
                    >
                        <LemonInput
                            value={groupBy}
                            placeholder="http.route"
                            disabled={saving}
                            onChange={setGroupBy}
                            fullWidth
                        />
                    </LemonField.Pure>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <LemonField.Pure label="Date range" help="Each value is the average over this range.">
                            <LemonSelect
                                value={dateFrom}
                                disabled={saving}
                                options={METRICS_TABLE_DATE_RANGE_OPTIONS}
                                onChange={(value) => value && setDateFrom(value)}
                                fullWidth
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            label="Point spacing"
                            help="Time between points on the full charts that open from a row. Sparklines show at most 30 points."
                        >
                            <LemonSelect
                                value={interval}
                                disabled={saving}
                                options={INTERVAL_OPTIONS}
                                onChange={setInterval}
                                fullWidth
                            />
                        </LemonField.Pure>
                    </div>
                    <div className="flex flex-col gap-2">
                        {columns.map((column, index) => (
                            <ColumnEditor key={index} column={column} index={index} />
                        ))}
                        <div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={addColumn}
                                disabledReason={
                                    columns.length >= METRICS_TABLE_MAX_COLUMNS
                                        ? `A table has at most ${METRICS_TABLE_MAX_COLUMNS} columns`
                                        : undefined
                                }
                            >
                                Add column
                            </LemonButton>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                        <LemonField.Pure label="Sort by">
                            <LemonSelect
                                value={orderByColumn}
                                disabled={saving || columns.length === 0}
                                options={columns.map((column, index) => ({ value: index, label: column.label }))}
                                onChange={(value) => value != null && setOrderByColumn(value)}
                                fullWidth
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Order">
                            <LemonSelect
                                value={orderDirection}
                                disabled={saving}
                                options={ORDER_DIRECTION_OPTIONS}
                                onChange={(value) => value && setOrderDirection(value)}
                                fullWidth
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Number of rows" help="Show up to 100 rows.">
                            <LemonInput
                                type="number"
                                min={1}
                                max={100}
                                value={limit}
                                disabled={saving}
                                onChange={(value) => setLimit(Number(value))}
                                fullWidth
                            />
                        </LemonField.Pure>
                    </div>
                </section>
            </div>
        </LemonModal>
    )
}

export function EditMetricsTableWidgetModal({ isOpen, ...props }: DashboardWidgetEditModalProps): JSX.Element | null {
    if (!isOpen) {
        return null
    }
    return (
        <BindLogic logic={editMetricsTableWidgetModalLogic} props={props}>
            <EditMetricsTableWidgetModalContents />
        </BindLogic>
    )
}
