import { dayjs } from 'lib/dayjs'

import {
    BIConfig,
    BISort,
    BIQueryLimit,
    BIAggregation,
    BIDateBucket,
    BIDataSource,
    BIField,
    BIValue,
    BIFilter,
    BIFilterOperator,
} from '~/queries/schema/schema-business-intelligence'
import {
    ChartSettings,
    DataVisualizationNode,
    DatabaseSchemaTable,
    DatabaseSerializedFieldType,
    HogQLQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    escapeDottedHogQLIdentifier,
    escapeHogQLString,
    escapePropertyAsHogQLIdentifier,
    escapeRawPropertyAsHogQLIdentifier,
} from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import {
    BI_TABLE_CALCULATIONS,
    buildBIAnalysisQuery,
    hasBIAnalysis,
    isBIAnalysisConfig,
    isBITableCalculation,
} from './biAnalysis'
import { getBIComparisonDisabledReason, getBIComparisonDateExpression } from './biComparison'
import { getBIFiltersPlaceholder, getBIQueryFilters, normalizeBIDates } from './biQueryFilters'

export enum BIEditorView {
    SQL = 'sql',
    BI = 'bi',
}

export type BIShelf = 'rows' | 'columns' | 'values' | 'filters'

export const BI_QUERY_LIMITS = [100, 1000, 10000, 50000] as const

export interface BISortOption {
    key: string
    label: string
    expression: string
}

export function getBIDataSourceKey(source: BIDataSource): string {
    return JSON.stringify([source.connectionId ?? null, source.table])
}

/** Keys an open editor by shelf too, because the same field can sit on several shelves at once. */
export function getBIShelfEditorKey(shelf: BIShelf, fieldId: string): string {
    return `${shelf}:${fieldId}`
}

export function getBIFieldId(source: BIDataSource, expression: string): string {
    return JSON.stringify([source.connectionId ?? null, source.table, expression])
}

export function changeBIFilterOperator(filter: BIFilter, operator: BIFilterOperator): BIFilter {
    const wasMultiple = ['in', 'not_in'].includes(filter.operator)
    const isMultiple = ['in', 'not_in'].includes(operator)
    if (wasMultiple === isMultiple) {
        return { ...filter, operator }
    }
    return {
        ...filter,
        operator,
        ...(isMultiple ? { values: filter.value ? [filter.value] : [] } : { value: filter.values?.[0] ?? '' }),
    }
}

export interface BIEditorState {
    editorView: BIEditorView
    config: BIConfig
}

export interface BIQueryBuildResult {
    query: string
    node: DataVisualizationNode
}

export function mergeBIChartSettings(
    current: ChartSettings | undefined,
    generated: ChartSettings | undefined
): ChartSettings | undefined {
    if (!generated) {
        if (current?.seriesBreakdownColumn) {
            const { xAxis, xAxisLabel, yAxis, seriesBreakdownColumn, showLegend, ...settings } = current
            return settings
        }
        return current
    }
    return {
        ...current,
        ...generated,
        xAxis: generated.xAxis
            ? {
                  ...(current?.xAxis?.column === generated.xAxis.column ? current.xAxis : {}),
                  ...generated.xAxis,
              }
            : current?.xAxis,
        yAxis:
            generated.yAxis?.map((axis) => ({
                ...current?.yAxis?.find((savedAxis) => savedAxis.column === axis.column),
                ...axis,
            })) ?? current?.yAxis,
        heatmap: current?.heatmap || generated.heatmap ? { ...current?.heatmap, ...generated.heatmap } : undefined,
    }
}

export const BI_FIELD_DRAG_MIME_TYPE = 'application/x-posthog-bi-field'

export const DEFAULT_BI_CONFIG: BIConfig = {
    source: null,
    chartType: ChartDisplayType.Auto,
    rows: [],
    columns: [],
    values: [],
    filters: [],
    limit: 1000,
    sort: null,
}

export function normalizeBIConfig(config: BIConfig): BIConfig {
    let normalized = normalizeBIDates(config)
    if (normalized.compareFilter?.compare && getBIComparisonDisabledReason(normalized)) {
        normalized = { ...normalized, compareFilter: { compare: false } }
    }
    const sort = normalized.sort
    if (sort && !getBISortOptions(normalized).some((option) => option.key === sort.key)) {
        normalized = { ...normalized, sort: null }
    }
    if (
        normalized.topN &&
        (![...normalized.rows, ...normalized.columns].some((field) => field.id === normalized.topN?.fieldId) ||
            normalized.topN.measureIndex >= Math.max(1, normalized.values.length))
    ) {
        normalized = { ...normalized, topN: undefined }
    }

    return normalized
}

const BI_AGGREGATIONS = new Set<BIAggregation>([
    'count',
    'count_distinct',
    'sum',
    'average',
    'minimum',
    'maximum',
    'custom',
])
const BI_FILTER_OPERATORS = new Set<BIFilterOperator>([
    'in',
    'not_in',
    'between',
    'equals',
    'not_equals',
    'contains',
    'greater_than',
    'less_than',
    'last_7_days',
    'is_set',
    'is_not_set',
    'custom',
])
const BI_DATE_BUCKETS = new Set<BIDateBucket>(['minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'])

const DATE_BUCKET_FUNCTIONS: Record<BIDateBucket, string> = {
    minute: 'toStartOfMinute',
    hour: 'toStartOfHour',
    day: 'toStartOfDay',
    week: 'toStartOfWeek',
    month: 'toStartOfMonth',
    quarter: 'toStartOfQuarter',
    year: 'toStartOfYear',
}

const DEFAULT_DATE_FIELD_BY_TABLE: Record<string, string> = {
    events: 'timestamp',
    sessions: '$start_timestamp',
    heatmaps: 'timestamp',
    session_replay_events: 'start_time',
    raw_session_replay_events: 'min_first_timestamp',
}

const NUMERIC_FIELD_TYPES = new Set<DatabaseSerializedFieldType>(['integer', 'float', 'decimal'])

export function isNumericBIField(field: BIField): boolean {
    return NUMERIC_FIELD_TYPES.has(field.type)
}

export function isDateTimeBIField(field: BIField): boolean {
    return field.type === 'date' || field.type === 'datetime'
}

export function isBIFieldCompatible(source: BIDataSource | null, field: BIField): boolean {
    return (
        !source ||
        (source.table === field.source.table && (source.connectionId ?? null) === (field.source.connectionId ?? null))
    )
}

export function defaultAggregationForField(field: BIField): BIAggregation {
    const baseTableName = field.source.table.replaceAll('`', '').split('.').pop() ?? field.source.table
    if (['id', 'uuid', `${baseTableName}_id`].includes(field.name)) {
        return 'count'
    }

    return isNumericBIField(field) ? 'sum' : 'count_distinct'
}

const IDENTIFIER_FIELD_NAME_REGEX = /(^|_)(id|uuid)$/i

/** Numeric fields that are not identifiers aggregate by default, like measures in a BI tool. */
export function isBIMeasureField(field: BIField): boolean {
    return (
        isNumericBIField(field) &&
        defaultAggregationForField(field) !== 'count' &&
        !IDENTIFIER_FIELD_NAME_REGEX.test(field.name.replace(/([a-z0-9])([A-Z])/g, '$1_$2'))
    )
}

export const BI_SHELF_PILL_DRAG_MIME_TYPE = 'application/x-posthog-bi-shelf-pill'

export interface BIShelfPillDragData {
    shelf: BIShelf
    index: number
    dragSessionId: string
}

export function parseBIShelfPillDragData(serialized: string): BIShelfPillDragData | null {
    try {
        const candidate = JSON.parse(serialized) as Partial<BIShelfPillDragData>
        if (
            ['rows', 'columns', 'values', 'filters'].includes(candidate.shelf as string) &&
            typeof candidate.index === 'number' &&
            Number.isInteger(candidate.index) &&
            candidate.index >= 0 &&
            typeof candidate.dragSessionId === 'string'
        ) {
            return { shelf: candidate.shelf as BIShelf, index: candidate.index, dragSessionId: candidate.dragSessionId }
        }
    } catch {
        return null
    }
    return null
}

/**
 * Where a field dropped from the data pane lands. Measures dropped on rows or columns are aggregated
 * rather than grouped, and exact timestamps are bucketed by day so grouping stays readable.
 */
export function getBIDropTarget(field: BIField, shelf: BIShelf): { field: BIField; shelf: BIShelf } {
    if ((shelf === 'rows' || shelf === 'columns') && isBIMeasureField(field)) {
        return { field, shelf: 'values' }
    }
    if ((shelf === 'rows' || shelf === 'columns') && field.type === 'datetime' && !field.dateBucket) {
        return { field: { ...field, dateBucket: 'day' }, shelf }
    }
    return { field, shelf }
}

const DATA_PANE_FIELD_TYPES = new Set<DatabaseSerializedFieldType>([
    'integer',
    'float',
    'decimal',
    'string',
    'datetime',
    'date',
    'boolean',
    'array',
    'json',
    'expression',
    'unknown',
])

export interface BIDataPaneFields {
    dimensions: BIField[]
    measures: BIField[]
}

export function getBIDataPaneFields(
    table: Pick<DatabaseSchemaTable, 'fields'> | undefined,
    source: BIDataSource,
    path: string[] = []
): BIDataPaneFields {
    const fields = Object.values(table?.fields ?? {})
        .filter((field) => DATA_PANE_FIELD_TYPES.has(field.type))
        .map((field): BIField => {
            const name = [...path, field.name].join('.')
            const expression = escapeDottedHogQLIdentifier(name)
            return { id: getBIFieldId(source, expression), name, expression, type: field.type, source }
        })
        .sort((first, second) => first.name.localeCompare(second.name))

    return {
        dimensions: fields.filter((field) => !isBIMeasureField(field)),
        measures: fields.filter(isBIMeasureField),
    }
}

export interface BIChartFit {
    fits: boolean
    requirement: string
}

/** Mirrors the "Show me" panel of desktop BI tools: which chart types suit the fields on the shelves. */
export function getBIChartFit(config: BIConfig, chartType: ChartDisplayType): BIChartFit {
    const rowCount = config.rows.length
    const columnCount = config.columns.length
    const dimensionCount = rowCount + columnCount
    const hasDateDimension = [...config.rows, ...config.columns].some(isDateTimeBIField)

    switch (chartType) {
        case ChartDisplayType.Auto:
            return { fits: true, requirement: 'Picks a chart type from the query results' }
        case ChartDisplayType.ActionsTable:
            return { fits: true, requirement: 'any combination of fields' }
        case ChartDisplayType.ActionsLineGraph:
        case ChartDisplayType.ActionsAreaGraph:
            return {
                fits: hasDateDimension && dimensionCount <= 2,
                requirement: '1 date, up to 1 more dimension, and any measures',
            }
        case ChartDisplayType.ActionsBar:
        case ChartDisplayType.ActionsStackedBar:
            return {
                fits: dimensionCount >= 1 && dimensionCount <= 2,
                requirement: '1 or 2 dimensions, and any measures',
            }
        case ChartDisplayType.ActionsPie:
        case ChartDisplayType.ActionsDonut:
            return {
                fits: dimensionCount === 1 && config.values.length <= 1,
                requirement: '1 dimension and up to 1 measure',
            }
        case ChartDisplayType.TwoDimensionalHeatmap:
            return {
                fits: rowCount >= 1 && columnCount >= 1 && config.values.length <= 1,
                requirement: '1 or more dimensions on rows and on columns, and up to 1 measure',
            }
        case ChartDisplayType.BoldNumber:
        case ChartDisplayType.Metric:
            return {
                fits: dimensionCount === 0 && config.values.length <= 1,
                requirement: 'no dimensions and up to 1 measure',
            }
        default:
            return { fits: true, requirement: '' }
    }
}

export function createDefaultDateFilter(source: BIDataSource): BIFilter | null {
    if (source.connectionId) {
        return null
    }

    const expression = DEFAULT_DATE_FIELD_BY_TABLE[source.table]
    if (!expression) {
        return null
    }

    return {
        field: {
            id: `bi-default:${source.table}:${expression}`,
            name: expression,
            expression,
            type: 'datetime',
            source,
        },
        operator: 'last_7_days',
        value: '',
    }
}

export function serializeBIField(field: BIField): string {
    return JSON.stringify(field)
}

function parseBIFieldValue(value: unknown): BIField | null {
    if (!value || typeof value !== 'object') {
        return null
    }

    const candidate = value as Partial<BIField>
    if (
        typeof candidate.id !== 'string' ||
        typeof candidate.name !== 'string' ||
        typeof candidate.expression !== 'string' ||
        typeof candidate.type !== 'string' ||
        (candidate.dateBucket !== undefined &&
            (!BI_DATE_BUCKETS.has(candidate.dateBucket) ||
                (candidate.type !== 'date' && candidate.type !== 'datetime'))) ||
        !candidate.source ||
        typeof candidate.source.table !== 'string' ||
        (candidate.source.connectionId !== undefined && typeof candidate.source.connectionId !== 'string')
    ) {
        return null
    }

    return candidate as BIField
}

export function parseBIField(serializedField: string): BIField | null {
    try {
        return parseBIFieldValue(JSON.parse(serializedField))
    } catch {
        return null
    }
}

export function parseBIEditorState(editorViewValue: unknown, configValue: unknown): BIEditorState | null {
    if (editorViewValue !== BIEditorView.SQL && editorViewValue !== BIEditorView.BI) {
        return null
    }

    if (configValue === undefined) {
        return {
            editorView: editorViewValue,
            config: { ...DEFAULT_BI_CONFIG, rows: [], columns: [], values: [], filters: [] },
        }
    }

    let decodedConfig = configValue
    if (typeof configValue === 'string') {
        try {
            decodedConfig = JSON.parse(configValue)
        } catch {
            return null
        }
    }
    if (!decodedConfig || typeof decodedConfig !== 'object') {
        return null
    }

    const candidate = decodedConfig as Partial<BIConfig>
    if (!isBIAnalysisConfig(candidate)) {
        return null
    }
    if (
        candidate.compareFilter !== undefined &&
        (!candidate.compareFilter ||
            typeof candidate.compareFilter !== 'object' ||
            (candidate.compareFilter.compare !== undefined && typeof candidate.compareFilter.compare !== 'boolean') ||
            (candidate.compareFilter.compare_to != null && typeof candidate.compareFilter.compare_to !== 'string'))
    ) {
        return null
    }
    if (
        candidate.dateRange !== undefined &&
        (!candidate.dateRange ||
            typeof candidate.dateRange !== 'object' ||
            [candidate.dateRange.date_from, candidate.dateRange.date_to].some(
                (bound) => bound != null && typeof bound !== 'string'
            ) ||
            (candidate.dateRange.explicitDate !== undefined && typeof candidate.dateRange.explicitDate !== 'boolean'))
    ) {
        return null
    }
    if (candidate.dateField !== undefined && candidate.dateField !== null && !parseBIFieldValue(candidate.dateField)) {
        return null
    }
    const source =
        candidate.source === null
            ? null
            : candidate.source &&
                typeof candidate.source.table === 'string' &&
                (candidate.source.connectionId === undefined || typeof candidate.source.connectionId === 'string')
              ? candidate.source
              : undefined
    const rows = Array.isArray(candidate.rows) ? candidate.rows.map(parseBIFieldValue) : null
    const columns = Array.isArray(candidate.columns) ? candidate.columns.map(parseBIFieldValue) : null
    const values = Array.isArray(candidate.values)
        ? candidate.values.map((value): BIValue | null => {
              if (!value || typeof value !== 'object') {
                  return null
              }
              const valueCandidate = value as Partial<BIValue>
              const field = parseBIFieldValue(valueCandidate.field)
              if (
                  !field ||
                  !BI_AGGREGATIONS.has(valueCandidate.aggregation as BIAggregation) ||
                  (valueCandidate.label !== undefined && typeof valueCandidate.label !== 'string') ||
                  (valueCandidate.tableCalculation !== undefined &&
                      !isBITableCalculation(valueCandidate.tableCalculation)) ||
                  (valueCandidate.customExpression !== undefined && typeof valueCandidate.customExpression !== 'string')
              ) {
                  return null
              }
              return {
                  field,
                  aggregation: valueCandidate.aggregation as BIAggregation,
                  customExpression: valueCandidate.customExpression,
                  label: valueCandidate.label,
                  ...(valueCandidate.tableCalculation ? { tableCalculation: valueCandidate.tableCalculation } : {}),
              }
          })
        : null
    const filters = Array.isArray(candidate.filters)
        ? candidate.filters.map((filter): BIFilter | null => {
              if (!filter || typeof filter !== 'object') {
                  return null
              }
              const filterCandidate = filter as Partial<BIFilter>
              const field = parseBIFieldValue(filterCandidate.field)
              if (
                  !field ||
                  !BI_FILTER_OPERATORS.has(filterCandidate.operator as BIFilterOperator) ||
                  typeof filterCandidate.value !== 'string' ||
                  (filterCandidate.values !== undefined &&
                      (!Array.isArray(filterCandidate.values) ||
                          !filterCandidate.values.every((value) => typeof value === 'string'))) ||
                  (filterCandidate.valueTo !== undefined && typeof filterCandidate.valueTo !== 'string') ||
                  (filterCandidate.enabled !== undefined && typeof filterCandidate.enabled !== 'boolean') ||
                  (filterCandidate.customExpression !== undefined &&
                      typeof filterCandidate.customExpression !== 'string')
              ) {
                  return null
              }
              return {
                  field,
                  operator: filterCandidate.operator as BIFilterOperator,
                  value: filterCandidate.value,
                  customExpression: filterCandidate.customExpression,
                  values: filterCandidate.values,
                  valueTo: filterCandidate.valueTo,
                  enabled: filterCandidate.enabled,
              }
          })
        : null
    const sortCandidate = candidate.sort
    // undefined tolerates states persisted before sort existed
    const sort: BISort | null | undefined =
        sortCandidate === undefined || sortCandidate === null
            ? null
            : typeof sortCandidate === 'object' &&
                typeof sortCandidate.key === 'string' &&
                (sortCandidate.direction === 'asc' || sortCandidate.direction === 'desc')
              ? { key: sortCandidate.key, direction: sortCandidate.direction }
              : undefined

    if (
        source === undefined ||
        sort === undefined ||
        !Object.values(ChartDisplayType).includes(candidate.chartType as ChartDisplayType) ||
        !rows ||
        rows.some((field) => !field) ||
        !columns ||
        columns.some((field) => !field) ||
        !values ||
        values.some((value) => !value) ||
        !filters ||
        filters.some((filter) => !filter) ||
        !BI_QUERY_LIMITS.includes(candidate.limit as BIQueryLimit)
    ) {
        return null
    }

    const config: BIConfig = {
        source,
        ...(candidate.topN ? { topN: candidate.topN } : {}),
        ...(candidate.totals ? { totals: candidate.totals } : {}),
        ...(candidate.compareFilter !== undefined ? { compareFilter: candidate.compareFilter } : {}),
        ...(candidate.dateField !== undefined
            ? { dateField: candidate.dateField === null ? null : parseBIFieldValue(candidate.dateField) }
            : {}),
        ...(candidate.dateRange !== undefined ? { dateRange: candidate.dateRange } : {}),
        chartType: candidate.chartType as ChartDisplayType,
        rows: rows as BIField[],
        columns: columns as BIField[],
        values: values as BIValue[],
        filters: filters as BIFilter[],
        limit: candidate.limit as BIQueryLimit,
        sort,
    }
    const fields = [
        ...config.rows,
        ...config.columns,
        ...config.values.map((value) => value.field),
        ...config.filters.map((filter) => filter.field),
        ...(config.dateField ? [config.dateField] : []),
    ]

    if (fields.length > 0 && (!source || fields.some((field) => !isBIFieldCompatible(source, field)))) {
        return null
    }

    return { editorView: editorViewValue, config: normalizeBIConfig(config) }
}

function sanitizeAlias(value: string): string {
    const alias = value
        .replaceAll(/[^a-zA-Z0-9_]+/g, '_')
        .replaceAll(/^_+|_+$/g, '')
        .toLowerCase()

    return alias || 'value'
}

function dimensionAlias(shelf: 'row' | 'column', field: BIField, index: number): string {
    return `bi_${shelf}_${sanitizeAlias(field.name || field.expression)}${index > 0 ? `_${index + 1}` : ''}`
}

interface BIDimension {
    alias: string
    field: BIField
}

interface BIPivotAxis {
    alias: string
    expression: string
    label: string
}

function aggregationAlias(value: BIValue, index: number): string {
    if (value.aggregation === 'custom' && value.label?.trim()) {
        return `${value.label.trim()}${index > 0 ? `_${index + 1}` : ''}`
    }
    return `${value.aggregation}_${sanitizeAlias(value.field.name)}${index > 0 ? `_${index + 1}` : ''}`
}

const DOTTED_IDENTIFIER_REGEX = /^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$/

function fieldExpression(field: BIField): string {
    const expression = field.expression.trim() || field.name
    const escapedExpression = DOTTED_IDENTIFIER_REGEX.test(expression)
        ? escapeDottedHogQLIdentifier(expression)
        : expression

    return field.dateBucket ? `${DATE_BUCKET_FUNCTIONS[field.dateBucket]}(${escapedExpression})` : escapedExpression
}

function pivotAxis(shelf: 'row' | 'column', dimensions: BIDimension[]): BIPivotAxis | null {
    if (dimensions.length === 0) {
        return null
    }

    return {
        alias: dimensions.length === 1 ? dimensions[0].alias : `bi_${shelf}s`,
        expression:
            dimensions.length === 1
                ? fieldExpression(dimensions[0].field)
                : `toJSONString(tuple(${dimensions.map(({ field }) => fieldExpression(field)).join(', ')}))`,
        label: dimensions.map(({ field }) => field.name || field.expression).join(' / '),
    }
}

function aggregationExpression(value: BIValue): string | null {
    if (value.aggregation === 'custom') {
        return value.customExpression?.trim() || null
    }

    const field = fieldExpression(value.field)

    if (!field) {
        return null
    }

    switch (value.aggregation) {
        case 'count':
            return `count(${field})`
        case 'count_distinct':
            return `count(DISTINCT ${field})`
        case 'sum':
            return `sum(${field})`
        case 'average':
            return `avg(${field})`
        case 'minimum':
            return `min(${field})`
        case 'maximum':
            return `max(${field})`
    }
}

export function getBIFilterValidationError(filter: BIFilter): string | null {
    if (
        filter.enabled === false ||
        !isNumericBIField(filter.field) ||
        ['custom', 'contains', 'is_set', 'is_not_set', 'last_7_days'].includes(filter.operator)
    ) {
        return null
    }
    const values =
        filter.operator === 'in' || filter.operator === 'not_in'
            ? (filter.values ?? [])
            : [filter.value, ...(filter.operator === 'between' ? [filter.valueTo ?? ''] : [])].filter(
                  (value) => value.trim() !== ''
              )
    return values.some(
        (value) =>
            !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim()) || !Number.isFinite(Number(value))
    )
        ? 'Enter a valid number for each filter value.'
        : null
}

export function getBIFilterSummary(filter: BIFilter): string {
    const dateFormat =
        filter.field.type === 'datetime' && filter.value.slice(0, 10) === filter.valueTo?.slice(0, 10)
            ? 'MMM D, HH:mm'
            : filter.value.slice(0, 4) !== filter.valueTo?.slice(0, 4)
              ? 'MMM D, YYYY'
              : 'MMM D'
    const formatValue = (value: string): string =>
        isDateTimeBIField(filter.field) && dayjs(value).isValid() ? dayjs(value).format(dateFormat) : value
    switch (filter.operator) {
        case 'in':
        case 'not_in': {
            const values = filter.values ?? []
            const selection = values.length === 1 ? values[0] || '(empty string)' : `${values.length} values`
            return values.length ? `${filter.operator === 'not_in' ? 'Except ' : ''}${selection}` : 'All values'
        }
        case 'between':
            return filter.value && filter.valueTo
                ? `${formatValue(filter.value)} to ${formatValue(filter.valueTo)}`
                : filter.value
                  ? `From ${formatValue(filter.value)}`
                  : filter.valueTo
                    ? `Up to ${formatValue(filter.valueTo)}`
                    : 'All values'
        case 'is_set':
            return 'Has a value'
        case 'is_not_set':
            return 'Has no value'
        case 'last_7_days':
            return 'Last 7 days'
        case 'custom':
            return filter.customExpression?.trim() || 'Add SQL condition'
        default: {
            const prefix = {
                equals: '',
                not_equals: 'Not ',
                contains: 'Contains ',
                greater_than: '> ',
                less_than: '< ',
            }[filter.operator]
            return filter.value ? `${prefix}${filter.value}` : 'All values'
        }
    }
}

function filterExpression(filter: BIFilter): string | null {
    if (filter.enabled === false) {
        return null
    }
    const field = fieldExpression(filter.field)

    if (filter.operator === 'custom') {
        return filter.customExpression?.trim() || null
    }

    if (filter.operator === 'is_set') {
        return `${field} IS NOT NULL`
    }
    if (filter.operator === 'is_not_set') {
        return `${field} IS NULL`
    }
    if (filter.operator === 'last_7_days') {
        return `(${field} >= now() - INTERVAL 7 DAY AND ${field} < now())`
    }
    // Strip leading zeroes so decimal input cannot become an octal HogQL literal.
    const literal = (value: string): string =>
        isNumericBIField(filter.field) ? value.trim().replace(/^([+-]?)0+(?=\d)/, '$1') : escapeHogQLString(value)
    if (filter.operator === 'in' || filter.operator === 'not_in') {
        const values = filter.values ?? []
        return values.length
            ? `${field} ${filter.operator === 'in' ? 'IN' : 'NOT IN'} (${values.map(literal).join(', ')})`
            : null
    }
    if (filter.operator === 'between') {
        const bounds = [
            filter.value.trim() ? `${field} >= ${literal(filter.value)}` : null,
            filter.valueTo?.trim() ? `${field} <= ${literal(filter.valueTo)}` : null,
        ].filter(Boolean)
        return bounds.length ? `(${bounds.join(' AND ')})` : null
    }
    if (!filter.value.trim()) {
        return null
    }

    const value = literal(filter.value)

    switch (filter.operator) {
        case 'equals':
            return `${field} = ${value}`
        case 'not_equals':
            return `${field} != ${value}`
        case 'contains':
            return `lower(${field}) LIKE lower(${escapeHogQLString(`%${filter.value}%`)})`
        case 'greater_than':
            return `${field} > ${value}`
        case 'less_than':
            return `${field} < ${value}`
    }
}

export function buildBIFilterOptionsQuery(config: BIConfig, index: number): HogQLQuery | null {
    config = normalizeBIConfig(config)
    const filter = config.filters[index]
    if (
        !config.source ||
        !filter?.field.expression.trim() ||
        config.filters.some((other, otherIndex) => otherIndex !== index && getBIFilterValidationError(other))
    ) {
        return null
    }
    const expression = fieldExpression(filter.field)
    const conditions = config.filters
        .filter(
            (other, otherIndex) =>
                otherIndex !== index &&
                (other.field.expression.trim() || other.field.name.trim() || other.operator === 'custom')
        )
        .map(filterExpression)
        .filter((condition): condition is string => !!condition)
    return {
        kind: NodeKind.HogQLQuery,
        connectionId: config.source.connectionId,
        filters: getBIQueryFilters(config),
        query: `SELECT DISTINCT toString(${expression}) AS value\nFROM ${escapePropertyAsHogQLIdentifier(config.source.table)}\nWHERE ${[getBIFiltersPlaceholder(config), `${expression} IS NOT NULL`, ...conditions].map((condition) => `(${condition})`).join(' AND ')}\nLIMIT 100`,
    }
}

interface BIConfiguredValue {
    value: BIValue
    expression: string
    alias: string
}

interface BIQueryParts {
    rowDimensions: BIDimension[]
    columnDimensions: BIDimension[]
    configuredValues: BIConfiguredValue[]
}

function computeBIQueryParts(config: BIConfig): BIQueryParts {
    const rowDimensions = config.rows
        .map((field, index) => ({ alias: dimensionAlias('row', field, index), field }))
        .filter(({ field }) => field.expression.trim() || field.name.trim())
    const columnDimensions = config.columns
        .map((field, index) => ({ alias: dimensionAlias('column', field, index), field }))
        .filter(({ field }) => field.expression.trim() || field.name.trim())
    const configuredValues = config.values
        .map((value) => ({ value, expression: aggregationExpression(value), alias: '' }))
        .filter((configuredValue): configuredValue is BIConfiguredValue => !!configuredValue.expression)

    const expressions = [
        ...rowDimensions.map(({ field }) => fieldExpression(field)),
        ...columnDimensions.map(({ field }) => fieldExpression(field)),
        ...configuredValues.map(({ expression }) => expression),
        ...config.filters.map((filter) => filter.customExpression || fieldExpression(filter.field)),
    ]
    const usedAliases = new Set([
        'bi_rows',
        'bi_columns',
        'bi_comparison',
        'bi_period',
        'bi_grouping',
        'bi_rank',
        ...[...rowDimensions, ...columnDimensions].map((_, index) => `bi_grouping_${index}`),
    ])
    for (const dimension of [...rowDimensions, ...columnDimensions]) {
        const preferred = dimension.alias
        let suffix = 2
        while (usedAliases.has(dimension.alias)) {
            dimension.alias = `${preferred}_${suffix++}`
        }
        usedAliases.add(dimension.alias)
    }
    const reservedAliases = new Set(configuredValues.map(({ value }, index) => aggregationAlias(value, index)))
    configuredValues.forEach((configuredValue, index) => {
        const preferred = aggregationAlias(configuredValue.value, index)
        let alias = preferred
        let suffix = 2
        // Avoid shadowing identifiers even inside authored formulas and SQL filters.
        while (
            usedAliases.has(alias) ||
            expressions.some(
                (expression) =>
                    expression.includes(alias) || expression.includes(escapeRawPropertyAsHogQLIdentifier(alias))
            )
        ) {
            do {
                alias = `${preferred}_${suffix++}`
            } while (reservedAliases.has(alias))
        }
        configuredValue.alias = alias
        usedAliases.add(alias)
    })

    return { rowDimensions, columnDimensions, configuredValues }
}

const SORT_AGGREGATION_LABELS: Record<Exclude<BIAggregation, 'custom'>, string> = {
    count: 'Count',
    count_distinct: 'Count distinct',
    sum: 'Sum',
    average: 'Average',
    minimum: 'Minimum',
    maximum: 'Maximum',
}

function sortValueLabel(value: BIValue): string {
    if (value.aggregation === 'custom') {
        return value.label?.trim() || value.customExpression?.trim() || 'Custom value'
    }

    return `${SORT_AGGREGATION_LABELS[value.aggregation]} of ${value.field.name || value.field.expression}`
}

export function getBISortOptions(config: BIConfig): BISortOption[] {
    if (!config.source) {
        return []
    }

    const { rowDimensions, columnDimensions, configuredValues } = computeBIQueryParts(config)
    // Without dimensions the query returns a single aggregate row, so there is nothing to sort
    if (rowDimensions.length === 0 && columnDimensions.length === 0) {
        return []
    }

    // The same field can back several value entries with different aggregations, so value keys
    // carry an occurrence suffix; the first occurrence keeps the unsuffixed key persisted states use
    const valueOccurrences = new Map<string, number>()
    const options: BISortOption[] = [
        ...rowDimensions.map(({ field }) => ({
            key: `rows:${field.id}`,
            label: field.name || field.expression,
            expression: fieldExpression(field),
        })),
        ...columnDimensions.map(({ field }) => ({
            key: `columns:${field.id}`,
            label: field.name || field.expression,
            expression: fieldExpression(field),
        })),
        ...(configuredValues.length > 0
            ? configuredValues.map(({ value, alias }) => {
                  const occurrence = valueOccurrences.get(value.field.id) ?? 0
                  valueOccurrences.set(value.field.id, occurrence + 1)
                  return {
                      key: occurrence === 0 ? `values:${value.field.id}` : `values:${value.field.id}:${occurrence + 1}`,
                      label: sortValueLabel(value),
                      expression: escapeRawPropertyAsHogQLIdentifier(alias),
                  }
              })
            : [{ key: 'values:count', label: 'Count', expression: 'count' }]),
    ]

    const seenKeys = new Set<string>()
    return options.filter((option) => {
        if (seenKeys.has(option.key)) {
            return false
        }
        seenKeys.add(option.key)
        return true
    })
}

/** The sort option key for the value at `index`, matching the keys `getBISortOptions` returns. */
export function getBIValueSortKey(config: BIConfig, index: number): string | null {
    const value = config.values[index]
    if (!value || !aggregationExpression(value)) {
        return null
    }
    const occurrence = config.values
        .slice(0, index)
        .filter((previous) => previous.field.id === value.field.id && !!aggregationExpression(previous)).length
    return occurrence === 0 ? `values:${value.field.id}` : `values:${value.field.id}:${occurrence + 1}`
}

const PILL_AGGREGATION_PREFIXES: Record<Exclude<BIAggregation, 'custom'>, string> = {
    count: 'COUNT',
    count_distinct: 'COUNTD',
    sum: 'SUM',
    average: 'AVG',
    minimum: 'MIN',
    maximum: 'MAX',
}

export function getBIFieldPillLabel(field: BIField): string {
    const name = field.name || field.expression.trim()
    if (!name) {
        return 'New calculation'
    }
    return field.dateBucket ? `${field.dateBucket.toUpperCase()}(${name})` : name
}

export function getBIValuePillLabel(value: BIValue): string {
    if (value.tableCalculation) {
        return `${BI_TABLE_CALCULATIONS.find((option) => option.value === value.tableCalculation?.type)?.label} · ${getBIValuePillLabel({ ...value, tableCalculation: undefined })}`
    }
    if (value.aggregation === 'custom') {
        return value.label?.trim() || value.customExpression?.trim() || 'New calculation'
    }
    return `${PILL_AGGREGATION_PREFIXES[value.aggregation]}(${getBIFieldPillLabel(value.field)})`
}

function buildOrderByExpression(
    config: BIConfig,
    dimensions: BIDimension[],
    configuredValues: BIConfiguredValue[]
): string | null {
    if (dimensions.length === 0) {
        return null
    }

    const sort = config.sort
    const selectedOption = sort ? getBISortOptions(config).find((option) => option.key === sort.key) : undefined
    if (sort && selectedOption) {
        return `${selectedOption.expression} ${sort.direction === 'asc' ? 'ASC' : 'DESC'}`
    }

    // Auto sort keeps the most relevant rows inside the LIMIT: newest first for date
    // dimensions, largest first otherwise
    const firstDimension = dimensions[0]
    if (isDateTimeBIField(firstDimension.field)) {
        return `${fieldExpression(firstDimension.field)} DESC`
    }

    const firstValueAlias =
        configuredValues.length > 0 ? escapeRawPropertyAsHogQLIdentifier(configuredValues[0].alias) : 'count'
    return `${firstValueAlias} DESC`
}

export function buildBIQuery(config: BIConfig, probeForMoreRows = false): BIQueryBuildResult | null {
    config = normalizeBIConfig(config)
    if (!config.source || config.filters.some(getBIFilterValidationError)) {
        return null
    }

    const { rowDimensions, columnDimensions, configuredValues } = computeBIQueryParts(config)
    const dimensions = [...rowDimensions, ...columnDimensions]
    const comparing = !!config.compareFilter?.compare
    const dimensionExpressions = dimensions.map(({ field }) => fieldExpression(field))
    const isPivotTable = config.chartType === ChartDisplayType.TwoDimensionalHeatmap
    const hasSeriesBreakdown =
        dimensions.length === 2 &&
        [
            ChartDisplayType.Auto,
            ChartDisplayType.ActionsBar,
            ChartDisplayType.ActionsStackedBar,
            ChartDisplayType.ActionsLineGraph,
            ChartDisplayType.ActionsAreaGraph,
        ].includes(config.chartType)
    const pivotRowAxis = isPivotTable ? pivotAxis('row', rowDimensions) : null
    const pivotColumnAxis = isPivotTable ? pivotAxis('column', columnDimensions) : null
    const dimensionSelectExpressions = isPivotTable
        ? [pivotRowAxis, pivotColumnAxis]
              .filter((axis): axis is BIPivotAxis => axis !== null)
              .map(({ alias, expression }) => `${expression} AS ${alias}`)
        : dimensions.map(({ field, alias }) =>
              hasSeriesBreakdown || comparing || hasBIAnalysis(config)
                  ? `${fieldExpression(field)} AS ${alias}`
                  : fieldExpression(field)
          )
    const valueExpressions =
        configuredValues.length > 0
            ? configuredValues.map(
                  ({ expression, alias }) => `${expression} AS ${escapeRawPropertyAsHogQLIdentifier(alias)}`
              )
            : ['count(*) AS count']
    const selectExpressions = [...dimensionSelectExpressions, ...valueExpressions]
    const filters = config.filters
        .filter(
            (filter) =>
                filter.field.expression.trim() ||
                filter.field.name.trim() ||
                (filter.operator === 'custom' && filter.customExpression?.trim())
        )
        .map(filterExpression)
        .filter((filter): filter is string => !!filter)
    const queryParts = [
        `SELECT\n    ${selectExpressions.join(',\n    ')}`,
        `FROM ${escapePropertyAsHogQLIdentifier(config.source.table)}`,
    ]

    queryParts.push(
        `WHERE\n    ${[getBIFiltersPlaceholder(config), ...filters.map((filter) => `(${filter})`)].join('\n    AND ')}`
    )
    if (dimensionExpressions.length > 0) {
        queryParts.push(`GROUP BY\n    ${dimensionExpressions.join(',\n    ')}`)
    }

    const orderByExpression = buildOrderByExpression(config, dimensions, configuredValues)
    if (orderByExpression) {
        queryParts.push(`ORDER BY\n    ${orderByExpression}`)
    }

    const resultLimit = normalizeBIConfig(config).limit + (probeForMoreRows ? 1 : 0)
    queryParts.push(`LIMIT ${resultLimit}`)

    let query = queryParts.join('\n')

    const chartDimensions = [...columnDimensions, ...rowDimensions]
    const xDimension = chartDimensions.find(({ field }) => isDateTimeBIField(field)) ?? chartDimensions[0]
    const breakdownDimension = chartDimensions.find((dimension) => dimension !== xDimension)
    let seriesSettings: ChartSettings | undefined =
        hasSeriesBreakdown && xDimension && breakdownDimension
            ? {
                  xAxis: { column: xDimension.alias },
                  xAxisLabel: getBIFieldPillLabel(xDimension.field),
                  yAxis:
                      configuredValues.length > 0
                          ? configuredValues.map(({ alias }) => ({ column: alias }))
                          : [{ column: 'count' }],
                  seriesBreakdownColumn: breakdownDimension.alias,
                  showLegend: true,
              }
            : undefined

    if (comparing) {
        const orderDimension = dimensions.find(({ field }) =>
            ['ASC', 'DESC'].some((direction) => orderByExpression === `${fieldExpression(field)} ${direction}`)
        )
        const comparisonOrder = orderDimension
            ? `${orderDimension.alias} ${orderByExpression?.endsWith(' ASC') ? 'ASC' : 'DESC'}`
            : orderByExpression
        const periodLabel = config.compareFilter?.compare_to ? 'Comparison period' : 'Previous period'
        const periodExpression = (label: string): string =>
            breakdownDimension
                ? `concat(${escapeHogQLString(label + ' · ')}, toString(${fieldExpression(breakdownDimension.field)}))`
                : escapeHogQLString(label)
        const buildPeriod = (previous: boolean): string => {
            const expressions = dimensions.map(({ field }) =>
                fieldExpression(
                    previous && isDateTimeBIField(field)
                        ? { ...field, expression: getBIComparisonDateExpression(field) }
                        : field
                )
            )
            const select = [
                ...dimensions.map(({ alias }, index) => `${expressions[index]} AS ${alias}`),
                ...valueExpressions,
                `${periodExpression(previous ? periodLabel : 'Current period')} AS bi_comparison`,
            ]
            const placeholder = getBIFiltersPlaceholder(config)
            return [
                `SELECT\n    ${select.join(',\n    ')}`,
                `FROM ${escapePropertyAsHogQLIdentifier(config.source!.table)}`,
                `WHERE\n    ${[previous ? placeholder.replace('{filters', '{filters.previous') : placeholder, ...filters.map((filter) => `(${filter})`)].join('\n    AND ')}`,
                ...(expressions.length ? [`GROUP BY ${[...expressions, 'bi_comparison'].join(', ')}`] : []),
                ...(comparisonOrder ? [`ORDER BY ${comparisonOrder}`] : []),
                `LIMIT ${resultLimit}`,
            ].join('\n')
        }
        query = `SELECT * FROM ((${buildPeriod(false)})\nUNION ALL\n(${buildPeriod(true)})) LIMIT ${resultLimit}`
        seriesSettings = {
            xAxis: { column: xDimension?.alias ?? 'bi_comparison' },
            xAxisLabel: xDimension ? getBIFieldPillLabel(xDimension.field) : 'Period',
            yAxis: configuredValues.length
                ? configuredValues.map(({ alias }) => ({ column: alias }))
                : [{ column: 'count' }],
            seriesBreakdownColumn: xDimension ? 'bi_comparison' : undefined,
            showLegend: true,
        }
    }

    const pivotTableSettings = isPivotTable
        ? {
              heatmap: {
                  xAxisColumn: pivotColumnAxis?.alias,
                  yAxisColumn: pivotRowAxis?.alias,
                  valueColumn: configuredValues[0]?.alias ?? 'count',
                  xAxisLabel: pivotColumnAxis?.label ?? 'Columns',
                  yAxisLabel: pivotRowAxis?.label ?? 'Rows',
              },
          }
        : undefined

    if (hasBIAnalysis(config)) {
        const placeholder = getBIFiltersPlaceholder(config)
        const where = (previous: boolean): string =>
            [
                previous ? placeholder.replace('{filters', '{filters.previous') : placeholder,
                ...filters.map((filter) => `(${filter})`),
            ].join(' AND ')
        query = buildBIAnalysisQuery(config, {
            rows: rowDimensions.map((dimension) => ({ ...dimension, expression: fieldExpression(dimension.field) })),
            columns: columnDimensions.map((dimension) => ({
                ...dimension,
                expression: fieldExpression(dimension.field),
            })),
            measures: configuredValues.length ? configuredValues : [{ alias: 'count', expression: 'count(*)' }],
            from: escapePropertyAsHogQLIdentifier(config.source.table),
            where: where(false),
            orderBy: orderByExpression,
            resultLimit,
            ...(comparing
                ? {
                      previousWhere: where(true),
                      previousDimensions: dimensions.map(({ field }) =>
                          fieldExpression(
                              isDateTimeBIField(field)
                                  ? {
                                        ...field,
                                        expression: getBIComparisonDateExpression(field),
                                    }
                                  : field
                          )
                      ),
                  }
                : {}),
        })
        seriesSettings ??= {
            xAxis: xDimension ? { column: xDimension.alias } : undefined,
            yAxis: configuredValues.length
                ? configuredValues.map(({ alias }) => ({ column: alias }))
                : [{ column: 'count' }],
        }
    }

    const calculatedFormats = configuredValues
        .filter(({ value }) => ['percent_of_total', 'percent_change'].includes(value.tableCalculation?.type ?? ''))
        .map(({ alias }) => ({
            column: alias,
            settings: { formatting: { style: 'percent' as const, decimalPlaces: 1 } },
        }))
    if (calculatedFormats.length) {
        seriesSettings = {
            ...seriesSettings,
            yAxis: (seriesSettings?.yAxis ?? configuredValues.map(({ alias }) => ({ column: alias }))).map((axis) => ({
                ...axis,
                ...calculatedFormats.find((format) => format.column === axis.column),
            })),
        }
    }

    return {
        query,
        node: {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query,
                connectionId: config.source.connectionId,
                sendRawQuery: undefined,
                filters: getBIQueryFilters(config),
            },
            display: config.chartType,
            ...(calculatedFormats.length
                ? {
                      tableSettings: {
                          columns: [
                              ...(isPivotTable
                                  ? [pivotRowAxis, pivotColumnAxis]
                                        .filter((axis): axis is BIPivotAxis => !!axis)
                                        .map((axis) => axis.alias)
                                  : dimensions.map((dimension) => dimension.alias)),
                              ...configuredValues.map((value) => value.alias),
                              ...(comparing ? ['bi_comparison'] : []),
                          ].map((column) => calculatedFormats.find((format) => format.column === column) ?? { column }),
                      },
                  }
                : {}),
            ...(pivotTableSettings || seriesSettings ? { chartSettings: pivotTableSettings ?? seriesSettings } : {}),
        },
    }
}
