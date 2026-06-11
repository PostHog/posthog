import { RowFilter, RowFilterOperator } from '~/types'

// Client-side mirror of the backend predicates classifier
// (posthog/temporal/data_imports/sources/common/sql/predicates.py). Kept in sync so the UI
// can validate before the PATCH; the backend re-validates and is the source of truth.

export type RowFilterColumnCategory =
    | 'integer'
    | 'numeric'
    | 'string'
    | 'boolean'
    | 'date'
    | 'timestamp'
    | 'unknown'

export const ROW_FILTER_OPERATORS: RowFilterOperator[] = ['>', '>=', '<', '<=', '=', '!=']

const OPERATOR_LABELS: Record<RowFilterOperator, string> = {
    '>': '> greater than',
    '>=': '≥ greater than or equal',
    '<': '< less than',
    '<=': '≤ less than or equal',
    '=': '= equals',
    '!=': '≠ not equal',
}

export function rowFilterOperatorLabel(operator: RowFilterOperator): string {
    return OPERATOR_LABELS[operator]
}

const INTEGER_TYPES = new Set([
    'int',
    'int2',
    'int4',
    'int8',
    'int16',
    'int32',
    'int64',
    'int128',
    'int256',
    'integer',
    'smallint',
    'mediumint',
    'bigint',
    'tinyint',
    'byteint',
    'serial',
    'smallserial',
    'bigserial',
    'uint8',
    'uint16',
    'uint32',
    'uint64',
    'uint128',
    'uint256',
])

const NUMERIC_TYPES = new Set([
    'numeric',
    'decimal',
    'real',
    'double',
    'double precision',
    'float',
    'float4',
    'float8',
    'float32',
    'float64',
    'number',
    'money',
    'smallmoney',
    'bignumeric',
    'dec',
    'fixed',
])

const STRING_TYPES = new Set([
    'char',
    'character',
    'character varying',
    'varchar',
    'varchar2',
    'nchar',
    'nvarchar',
    'nvarchar2',
    'text',
    'tinytext',
    'mediumtext',
    'longtext',
    'ntext',
    'string',
    'fixedstring',
    'clob',
    'nclob',
    'uuid',
    'uniqueidentifier',
    'name',
    'citext',
    'enum',
    'json',
    'jsonb',
])

const BOOLEAN_TYPES = new Set(['bool', 'boolean', 'bit'])
const DATE_TYPES = new Set(['date', 'date32'])
const TIMESTAMP_TYPES = new Set([
    'timestamp',
    'timestamptz',
    'timestamp with time zone',
    'timestamp without time zone',
    'datetime',
    'datetime2',
    'datetime64',
    'smalldatetime',
    'datetimeoffset',
])

function stripNullableWrappers(dataType: string): string {
    let current = dataType.trim()
    // eslint-disable-next-line no-constant-condition
    while (true) {
        if (current.startsWith('Nullable(') && current.endsWith(')')) {
            current = current.slice('Nullable('.length, -1).trim()
        } else if (current.startsWith('LowCardinality(') && current.endsWith(')')) {
            current = current.slice('LowCardinality('.length, -1).trim()
        } else {
            return current
        }
    }
}

function stripTypeParams(dataType: string): string {
    const paren = dataType.indexOf('(')
    return (paren === -1 ? dataType : dataType.slice(0, paren)).trim()
}

export function classifyColumnType(dataType: string | undefined | null): RowFilterColumnCategory {
    if (!dataType || !dataType.trim()) {
        return 'unknown'
    }
    const base = stripTypeParams(stripNullableWrappers(dataType)).toLowerCase()
    if (INTEGER_TYPES.has(base)) {
        return 'integer'
    }
    if (NUMERIC_TYPES.has(base)) {
        return 'numeric'
    }
    if (BOOLEAN_TYPES.has(base)) {
        return 'boolean'
    }
    if (DATE_TYPES.has(base)) {
        return 'date'
    }
    if (STRING_TYPES.has(base)) {
        return 'string'
    }
    if (TIMESTAMP_TYPES.has(base) || base.startsWith('timestamp') || base.startsWith('datetime')) {
        return 'timestamp'
    }
    return 'unknown'
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$/

/**
 * Validate a single filter's value against the column's type category. Returns an error
 * string to show the user, or `null` when the value is acceptable. Mirrors the backend
 * coercion rules closely enough to catch mistakes before the request goes out.
 */
export function validateRowFilterValue(
    category: RowFilterColumnCategory,
    value: string | number | boolean
): string | null {
    switch (category) {
        case 'unknown':
            return 'This column type is not supported for filtering'
        case 'boolean':
            if (typeof value === 'boolean') {
                return null
            }
            return 'Pick true or false'
        case 'integer': {
            const raw = String(value).trim()
            if (raw === '' || !/^[+-]?\d+$/.test(raw)) {
                return 'Enter a whole number'
            }
            return null
        }
        case 'numeric': {
            const raw = String(value).trim()
            if (raw === '' || !Number.isFinite(Number(raw))) {
                return 'Enter a number'
            }
            return null
        }
        case 'string':
            return typeof value === 'string' ? null : 'Enter a text value'
        case 'date': {
            const raw = String(value).trim()
            if (!ISO_DATE.test(raw) || Number.isNaN(Date.parse(raw))) {
                return 'Enter a date as YYYY-MM-DD'
            }
            return null
        }
        case 'timestamp': {
            const raw = String(value).trim()
            if (!ISO_DATETIME.test(raw) || Number.isNaN(Date.parse(raw))) {
                return 'Enter a date or timestamp (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)'
            }
            return null
        }
    }
}

export interface RowFilterValidationContext {
    availableColumns: { name: string; data_type?: string }[]
}

/**
 * Validate the full list of filters. Returns a per-index error map (empty when all valid).
 * A filter is invalid if its column is unknown, its operator is disallowed, or its value
 * doesn't match the column's type.
 */
export function validateRowFilters(
    filters: RowFilter[],
    { availableColumns }: RowFilterValidationContext
): Record<number, string> {
    const typeByColumn = new Map(availableColumns.map((c) => [c.name, c.data_type]))
    const errors: Record<number, string> = {}
    filters.forEach((filter, index) => {
        if (!filter.column) {
            errors[index] = 'Pick a column'
            return
        }
        if (!typeByColumn.has(filter.column)) {
            errors[index] = `Unknown column "${filter.column}"`
            return
        }
        if (!ROW_FILTER_OPERATORS.includes(filter.operator)) {
            errors[index] = 'Pick an operator'
            return
        }
        const category = classifyColumnType(typeByColumn.get(filter.column))
        const valueError = validateRowFilterValue(category, filter.value)
        if (valueError) {
            errors[index] = valueError
        }
    })
    return errors
}
