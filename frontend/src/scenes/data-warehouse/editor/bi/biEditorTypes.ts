import { DataVisualizationNode, DatabaseSerializedFieldType, NodeKind } from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier, escapeHogQLString, escapePropertyAsHogQLIdentifier } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

export enum BIEditorView {
    SQL = 'sql',
    BI = 'bi',
}

export type BIShelf = 'rows' | 'columns' | 'values' | 'filters'

export type BIAggregation = 'count' | 'count_distinct' | 'sum' | 'average' | 'minimum' | 'maximum' | 'custom'

export type BIDateBucket = 'minute' | 'hour' | 'day' | 'week' | 'month' | 'quarter' | 'year'

export type BIFilterOperator =
    | 'equals'
    | 'not_equals'
    | 'contains'
    | 'greater_than'
    | 'less_than'
    | 'last_7_days'
    | 'is_set'
    | 'is_not_set'
    | 'custom'

export interface BIDataSource {
    table: string
    connectionId?: string
}

export function getBIDataSourceKey(source: BIDataSource): string {
    return JSON.stringify([source.connectionId ?? null, source.table])
}

export function getBIFieldId(source: BIDataSource, expression: string): string {
    return JSON.stringify([source.connectionId ?? null, source.table, expression])
}

export interface BIField {
    id: string
    name: string
    expression: string
    type: DatabaseSerializedFieldType
    source: BIDataSource
    dateBucket?: BIDateBucket
}

export interface BIValue {
    field: BIField
    aggregation: BIAggregation
    customExpression?: string
}

export interface BIFilter {
    field: BIField
    operator: BIFilterOperator
    value: string
    customExpression?: string
}

export interface BIConfig {
    source: BIDataSource | null
    chartType: ChartDisplayType
    rows: BIField[]
    columns: BIField[]
    values: BIValue[]
    filters: BIFilter[]
    limit: number
}

export interface BIEditorState {
    editorView: BIEditorView
    config: BIConfig
}

export interface BIQueryBuildResult {
    query: string
    node: DataVisualizationNode
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
                  (valueCandidate.customExpression !== undefined && typeof valueCandidate.customExpression !== 'string')
              ) {
                  return null
              }
              return {
                  field,
                  aggregation: valueCandidate.aggregation as BIAggregation,
                  customExpression: valueCandidate.customExpression,
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
              }
          })
        : null

    if (
        source === undefined ||
        !Object.values(ChartDisplayType).includes(candidate.chartType as ChartDisplayType) ||
        !rows ||
        rows.some((field) => !field) ||
        !columns ||
        columns.some((field) => !field) ||
        !values ||
        values.some((value) => !value) ||
        !filters ||
        filters.some((filter) => !filter) ||
        typeof candidate.limit !== 'number' ||
        !Number.isInteger(candidate.limit) ||
        candidate.limit <= 0
    ) {
        return null
    }

    const config: BIConfig = {
        source,
        chartType: candidate.chartType as ChartDisplayType,
        rows: rows as BIField[],
        columns: columns as BIField[],
        values: values as BIValue[],
        filters: filters as BIFilter[],
        limit: candidate.limit,
    }
    const fields = [
        ...config.rows,
        ...config.columns,
        ...config.values.map((value) => value.field),
        ...config.filters.map((filter) => filter.field),
    ]

    if (fields.length > 0 && (!source || fields.some((field) => !isBIFieldCompatible(source, field)))) {
        return null
    }

    return { editorView: editorViewValue, config }
}

function sanitizeAlias(value: string): string {
    const alias = value
        .replaceAll(/[^a-zA-Z0-9_]+/g, '_')
        .replaceAll(/^_+|_+$/g, '')
        .toLowerCase()

    return alias || 'value'
}

const DOTTED_IDENTIFIER_REGEX = /^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$/

function fieldExpression(field: BIField): string {
    const expression = field.expression.trim() || field.name
    const escapedExpression = DOTTED_IDENTIFIER_REGEX.test(expression)
        ? escapeDottedHogQLIdentifier(expression)
        : expression

    return field.dateBucket ? `${DATE_BUCKET_FUNCTIONS[field.dateBucket]}(${escapedExpression})` : escapedExpression
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

function filterExpression(filter: BIFilter): string | null {
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
        return `${field} >= now() - INTERVAL 7 DAY`
    }
    if (!filter.value.trim()) {
        return null
    }

    const value =
        isNumericBIField(filter.field) && Number.isFinite(Number(filter.value))
            ? String(Number(filter.value))
            : escapeHogQLString(filter.value)

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

export function buildBIQuery(config: BIConfig): BIQueryBuildResult | null {
    if (!config.source) {
        return null
    }

    const dimensions = [...config.rows, ...config.columns].filter(
        (field) => field.expression.trim() || field.name.trim()
    )
    const dimensionExpressions = dimensions.map(fieldExpression)
    const configuredValues = config.values
        .map((value) => ({ value, expression: aggregationExpression(value) }))
        .filter(
            (configuredValue): configuredValue is { value: BIValue; expression: string } => !!configuredValue.expression
        )
    const valueExpressions =
        configuredValues.length > 0
            ? configuredValues.map(({ value, expression }, index) => {
                  const alias = `${value.aggregation}_${sanitizeAlias(value.field.name)}${index > 0 ? `_${index + 1}` : ''}`
                  return `${expression} AS ${escapePropertyAsHogQLIdentifier(alias)}`
              })
            : ['count(*) AS count']
    const selectExpressions = [...dimensionExpressions, ...valueExpressions]
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

    if (filters.length > 0) {
        queryParts.push(`WHERE\n    ${filters.join('\n    AND ')}`)
    }
    if (dimensionExpressions.length > 0) {
        queryParts.push(`GROUP BY\n    ${dimensionExpressions.join(',\n    ')}`)
    }

    queryParts.push(`LIMIT ${config.limit}`)

    const query = queryParts.join('\n')

    return {
        query,
        node: {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query,
                connectionId: config.source.connectionId,
            },
            display: config.chartType,
        },
    }
}
