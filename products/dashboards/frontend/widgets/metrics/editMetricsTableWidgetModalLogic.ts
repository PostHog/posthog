import { MakeLogicType, actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { MetricsTableWidgetConfig } from '../../generated/widget-configs.zod'
import { metricsTableWidgetConfigSchema } from '../../generated/widget-configs.zod'
import type { WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import {
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
    widgetEditModalTileActions,
} from '../editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from '../registry'
import {
    METRICS_TABLE_MAX_LIMIT,
    type MetricsTableAggregation,
    type MetricsTableColumn,
    parseMetricsTableWidgetConfig,
} from './metricsTableWidgetConfigValidation'

export type EditMetricsTableWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>
export type MetricsTableOrderDirection = 'ASC' | 'DESC'
export type MetricsTableInterval = NonNullable<MetricsTableWidgetConfig['interval']>

export const METRICS_TABLE_MAX_COLUMNS = 6
const DEFAULT_QUANTILE = 0.95
const NEW_COLUMN: MetricsTableColumn = { label: 'Value', metricName: '', aggregation: 'avg' }

export interface editMetricsTableWidgetModalLogicValues {
    columnMetricTypes: (string | null)[]
    columns: MetricsTableColumn[]
    config: MetricsTableWidgetConfig
    dateFrom: WidgetDateFromValue
    defaultTitle: string
    groupBy: string
    interval: MetricsTableInterval | null
    limit: number
    onClose: () => void
    orderByColumn: number
    orderDirection: MetricsTableOrderDirection
    saveDisabledReason: string | undefined
    saving: boolean
    tileDescription: string
    tileName: string
}

export interface editMetricsTableWidgetModalLogicActions {
    addColumn: () => { value: true }
    loadConfig: (config: MetricsTableWidgetConfig) => { config: MetricsTableWidgetConfig }
    removeColumn: (index: number) => { index: number }
    selectColumnMetric: (
        index: number,
        metricName: string,
        metricType?: string
    ) => { index: number; metricName: string; metricType: string | null }
    setDateFrom: (dateFrom: WidgetDateFromValue) => { dateFrom: WidgetDateFromValue }
    setGroupBy: (groupBy: string) => { groupBy: string }
    setInterval: (interval: MetricsTableInterval | null) => { interval: MetricsTableInterval | null }
    setLimit: (limit: number) => { limit: number }
    setOrderByColumn: (orderByColumn: number) => { orderByColumn: number }
    setOrderDirection: (orderDirection: MetricsTableOrderDirection) => {
        orderDirection: MetricsTableOrderDirection
    }
    setTileDescription: (tileDescription: string) => { tileDescription: string }
    setTileName: (tileName: string) => { tileName: string }
    submit: () => { value: true }
    submitFailure: () => { value: true }
    submitSuccess: () => { value: true }
    updateColumn: (
        index: number,
        patch: Partial<MetricsTableColumn>
    ) => { index: number; patch: Partial<MetricsTableColumn> }
}

export type editMetricsTableWidgetModalLogicType = MakeLogicType<
    editMetricsTableWidgetModalLogicValues,
    editMetricsTableWidgetModalLogicActions,
    EditMetricsTableWidgetModalLogicProps
>

// Ingestion flattens an exponential histogram into explicit buckets, so a percentile works on both.
const HISTOGRAM_METRIC_TYPES = new Set(['histogram', 'exponential_histogram'])

/** Why a calculation does not fit a metric of this type. Only a histogram has buckets for a percentile. */
export function metricsTableAggregationDisabledReason(
    metricType: string | null | undefined,
    aggregation: MetricsTableAggregation
): string | undefined {
    if (!metricType) {
        return undefined
    }
    if (HISTOGRAM_METRIC_TYPES.has(metricType)) {
        return aggregation === 'histogram_quantile' ? undefined : 'A histogram metric needs a percentile'
    }
    return aggregation === 'histogram_quantile' ? 'A percentile needs a histogram metric' : undefined
}

function fittingAggregation(column: MetricsTableColumn, metricType: string): MetricsTableAggregation {
    const { aggregation } = column
    // A new column starts as an average, and the average of a running counter total means nothing.
    if (metricType === 'sum' && !column.metricName && aggregation === NEW_COLUMN.aggregation) {
        return 'rate'
    }
    if (!metricsTableAggregationDisabledReason(metricType, aggregation)) {
        return aggregation
    }
    if (HISTOGRAM_METRIC_TYPES.has(metricType)) {
        return 'histogram_quantile'
    }
    return metricType === 'sum' ? 'rate' : 'avg'
}

/** A histogram quantile needs a quantile, and every other aggregation must not have one. */
function withQuantileRule(column: MetricsTableColumn): MetricsTableColumn {
    if (column.aggregation === 'histogram_quantile') {
        return { ...column, quantile: column.quantile ?? DEFAULT_QUANTILE }
    }
    const { quantile: _quantile, ...rest } = column
    return rest
}

export const editMetricsTableWidgetModalLogic = kea<editMetricsTableWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'metrics', 'editMetricsTableWidgetModalLogic']),
    props({} as EditMetricsTableWidgetModalLogicProps),
    actions({
        ...widgetEditModalTileActions,
        loadConfig: (config: MetricsTableWidgetConfig) => ({ config }),
        setGroupBy: (groupBy: string) => ({ groupBy }),
        setDateFrom: (dateFrom: WidgetDateFromValue) => ({ dateFrom }),
        setInterval: (interval: MetricsTableInterval | null) => ({ interval }),
        setLimit: (limit: number) => ({ limit }),
        setOrderByColumn: (orderByColumn: number) => ({ orderByColumn }),
        setOrderDirection: (orderDirection: MetricsTableOrderDirection) => ({ orderDirection }),
        addColumn: true,
        removeColumn: (index: number) => ({ index }),
        selectColumnMetric: (index: number, metricName: string, metricType?: string) => ({
            index,
            metricName,
            metricType: metricType || null,
        }),
        updateColumn: (index: number, patch: Partial<MetricsTableColumn>) => ({ index, patch }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),
    reducers({
        groupBy: [
            '',
            {
                loadConfig: (_state: string, { config }: { config: MetricsTableWidgetConfig }) => config.groupBy ?? '',
                setGroupBy: (_state: string, { groupBy }: { groupBy: string }) => groupBy,
            },
        ],
        dateFrom: [
            '-1h' as WidgetDateFromValue,
            {
                loadConfig: (_state: WidgetDateFromValue, { config }: { config: MetricsTableWidgetConfig }) =>
                    config.dateRange?.date_from ?? '-1h',
                setDateFrom: (_state: WidgetDateFromValue, { dateFrom }: { dateFrom: WidgetDateFromValue }) => dateFrom,
            },
        ],
        interval: [
            null as MetricsTableInterval | null,
            {
                loadConfig: (_state: MetricsTableInterval | null, { config }: { config: MetricsTableWidgetConfig }) =>
                    config.interval ?? null,
                setInterval: (
                    _state: MetricsTableInterval | null,
                    { interval }: { interval: MetricsTableInterval | null }
                ) => interval,
            },
        ],
        limit: [
            25,
            {
                loadConfig: (_state: number, { config }: { config: MetricsTableWidgetConfig }) => config.limit ?? 25,
                setLimit: (_state: number, { limit }: { limit: number }) => limit,
            },
        ],
        orderDirection: [
            'DESC' as MetricsTableOrderDirection,
            {
                loadConfig: (_state: MetricsTableOrderDirection, { config }: { config: MetricsTableWidgetConfig }) =>
                    config.orderDirection ?? 'DESC',
                setOrderDirection: (
                    _state: MetricsTableOrderDirection,
                    { orderDirection }: { orderDirection: MetricsTableOrderDirection }
                ) => orderDirection,
            },
        ],
        orderByColumn: [
            0,
            {
                loadConfig: (_state: number, { config }: { config: MetricsTableWidgetConfig }) =>
                    config.orderByColumn ?? 0,
                setOrderByColumn: (_state: number, { orderByColumn }: { orderByColumn: number }) => orderByColumn,
                removeColumn: (state: number, { index }: { index: number }) =>
                    index < state ? state - 1 : index === state ? 0 : state,
            },
        ],
        columns: [
            [] as MetricsTableColumn[],
            {
                loadConfig: (_state: MetricsTableColumn[], { config }: { config: MetricsTableWidgetConfig }) =>
                    config.columns ?? [],
                addColumn: (state: MetricsTableColumn[]) =>
                    state.length < METRICS_TABLE_MAX_COLUMNS ? [...state, NEW_COLUMN] : state,
                removeColumn: (state: MetricsTableColumn[], { index }: { index: number }) =>
                    state.filter((_, columnIndex) => columnIndex !== index),
                updateColumn: (
                    state: MetricsTableColumn[],
                    { index, patch }: { index: number; patch: Partial<MetricsTableColumn> }
                ) =>
                    state.map((column, columnIndex) =>
                        columnIndex === index ? withQuantileRule({ ...column, ...patch }) : column
                    ),
                selectColumnMetric: (
                    state: MetricsTableColumn[],
                    { index, metricName, metricType }: { index: number; metricName: string; metricType: string | null }
                ) =>
                    state.map((column, columnIndex) =>
                        columnIndex === index
                            ? withQuantileRule({
                                  ...column,
                                  metricName,
                                  aggregation: metricType ? fittingAggregation(column, metricType) : column.aggregation,
                              })
                            : column
                    ),
            },
        ],
        // The picker knows a metric's type. A saved column has no type here until the user picks its metric again.
        columnMetricTypes: [
            [] as (string | null)[],
            {
                loadConfig: (_state: (string | null)[], { config }: { config: MetricsTableWidgetConfig }) =>
                    (config.columns ?? []).map(() => null),
                addColumn: (state: (string | null)[]) =>
                    state.length < METRICS_TABLE_MAX_COLUMNS ? [...state, null] : state,
                removeColumn: (state: (string | null)[], { index }: { index: number }) =>
                    state.filter((_, columnIndex) => columnIndex !== index),
                selectColumnMetric: (
                    state: (string | null)[],
                    { index, metricType }: { index: number; metricType: string | null }
                ) => state.map((type, columnIndex) => (columnIndex === index ? metricType : type)),
            },
        ],
        tileName: ['', { setTileName: (_state: string, { tileName }: { tileName: string }) => tileName }],
        tileDescription: [
            '',
            {
                setTileDescription: (_state: string, { tileDescription }: { tileDescription: string }) =>
                    tileDescription,
            },
        ],
        saving: [false, { submit: () => true, submitSuccess: () => false, submitFailure: () => false }],
        defaultTitle: ['Metrics table'],
    }),
    selectors({
        config: [
            (s) => [s.groupBy, s.columns, s.dateFrom, s.interval, s.limit, s.orderByColumn, s.orderDirection],
            (
                groupBy: string,
                columns: MetricsTableColumn[],
                dateFrom: WidgetDateFromValue,
                interval: MetricsTableInterval | null,
                limit: number,
                orderByColumn: number,
                orderDirection: MetricsTableOrderDirection
            ): MetricsTableWidgetConfig => ({
                groupBy: groupBy.trim() || null,
                columns: columns.map((column) => ({ ...column, metricName: column.metricName.trim() })),
                dateRange: { date_from: dateFrom },
                interval,
                limit,
                orderByColumn,
                orderDirection,
            }),
        ],
        saveDisabledReason: [
            (s) => [s.config],
            (config: MetricsTableWidgetConfig): string | undefined => {
                if (!config.groupBy) {
                    return 'Enter a label to make one row per value'
                }
                const columns: MetricsTableColumn[] = config.columns ?? []
                if (!columns.length) {
                    return 'Add at least one column'
                }
                if (columns.some((column) => !column.metricName)) {
                    return 'Pick a metric for every column'
                }
                if (columns.some((column) => !column.label.trim())) {
                    return 'Name every column'
                }
                if (
                    !Number.isInteger(config.limit) ||
                    (config.limit ?? 0) < 1 ||
                    (config.limit ?? 0) > METRICS_TABLE_MAX_LIMIT
                ) {
                    return `Enter a whole number of rows from 1 to ${METRICS_TABLE_MAX_LIMIT}`
                }
                return metricsTableWidgetConfigSchema.safeParse(config).success
                    ? undefined
                    : 'Check the column settings'
            },
        ],
        onClose: [(_state, props) => [props.onClose], (onClose): (() => void) => onClose],
    }),
    listeners(({ actions, values, props }) => ({
        submit: async () => {
            try {
                const config = metricsTableWidgetConfigSchema.parse(values.config)
                await props.onSave(config, buildWidgetTileMetadataPatch(props, values.tileName, values.tileDescription))
                actions.submitSuccess()
                props.onClose()
            } catch {
                actions.submitFailure()
                lemonToast.error('Could not save widget settings. Check your connection and try again.')
            }
        },
    })),
    afterMount(({ actions, props }) => {
        const metadata = getWidgetEditModalTileDefaults(props)
        actions.loadConfig(parseMetricsTableWidgetConfig(props.config))
        actions.setTileName(metadata.tileName)
        actions.setTileDescription(metadata.tileDescription)
    }),
])
