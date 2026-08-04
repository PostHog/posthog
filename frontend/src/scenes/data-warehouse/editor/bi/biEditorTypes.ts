import { DataVisualizationNode, DatabaseSerializedFieldType, NodeKind } from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier, escapeHogQLString, escapePropertyAsHogQLIdentifier } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

export enum BIEditorView {
    SQL = 'sql',
    BI = 'bi',
}

export type BIShelf = 'rows' | 'columns' | 'values' | 'filters'

export type BIAggregation = 'count' | 'count_distinct' | 'sum' | 'average' | 'minimum' | 'maximum'

export type BIFilterOperator =
    | 'equals'
    | 'not_equals'
    | 'contains'
    | 'greater_than'
    | 'less_than'
    | 'is_set'
    | 'is_not_set'

export interface BIDataSource {
    table: string
    connectionId?: string
}

export interface BIField {
    id: string
    name: string
    expression: string
    type: DatabaseSerializedFieldType
    source: BIDataSource
}

export interface BIValue {
    field: BIField
    aggregation: BIAggregation
}

export interface BIFilter {
    field: BIField
    operator: BIFilterOperator
    value: string
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

const NUMERIC_FIELD_TYPES = new Set<DatabaseSerializedFieldType>(['integer', 'float', 'decimal'])

export function isNumericBIField(field: BIField): boolean {
    return NUMERIC_FIELD_TYPES.has(field.type)
}

export function isBIFieldCompatible(source: BIDataSource | null, field: BIField): boolean {
    return (
        !source ||
        (source.table === field.source.table && (source.connectionId ?? null) === (field.source.connectionId ?? null))
    )
}

export function defaultAggregationForField(field: BIField): BIAggregation {
    return isNumericBIField(field) ? 'sum' : 'count_distinct'
}

export function serializeBIField(field: BIField): string {
    return JSON.stringify(field)
}

export function parseBIField(serializedField: string): BIField | null {
    try {
        const value: unknown = JSON.parse(serializedField)
        if (!value || typeof value !== 'object') {
            return null
        }

        const candidate = value as Partial<BIField>
        if (
            typeof candidate.id !== 'string' ||
            typeof candidate.name !== 'string' ||
            typeof candidate.expression !== 'string' ||
            typeof candidate.type !== 'string' ||
            !candidate.source ||
            typeof candidate.source.table !== 'string'
        ) {
            return null
        }

        return candidate as BIField
    } catch {
        return null
    }
}

function sanitizeAlias(value: string): string {
    const alias = value
        .replaceAll(/[^a-zA-Z0-9_]+/g, '_')
        .replaceAll(/^_+|_+$/g, '')
        .toLowerCase()

    return alias || 'value'
}

function aggregationExpression(value: BIValue): string {
    const field = escapeDottedHogQLIdentifier(value.field.expression)

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
    const field = escapeDottedHogQLIdentifier(filter.field.expression)

    if (filter.operator === 'is_set') {
        return `${field} IS NOT NULL`
    }
    if (filter.operator === 'is_not_set') {
        return `${field} IS NULL`
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

    const dimensions = [...config.rows, ...config.columns]
    const dimensionExpressions = dimensions.map((field) => escapeDottedHogQLIdentifier(field.expression))
    const valueExpressions =
        config.values.length > 0
            ? config.values.map((value, index) => {
                  const alias = `${value.aggregation}_${sanitizeAlias(value.field.name)}${index > 0 ? `_${index + 1}` : ''}`
                  return `${aggregationExpression(value)} AS ${escapePropertyAsHogQLIdentifier(alias)}`
              })
            : ['count(*) AS count']
    const selectExpressions = [...dimensionExpressions, ...valueExpressions]
    const filters = config.filters.map(filterExpression).filter((filter): filter is string => !!filter)
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
