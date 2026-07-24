import { splitQueries } from 'scenes/data-warehouse/editor/multiQueryUtils'

import {
    InsightBuilderAggregation,
    InsightBuilderConfig,
    InsightBuilderDateGrain,
    InsightBuilderDimension,
    InsightBuilderFilter,
    InsightBuilderMeasure,
} from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier, escapePropertyAsHogQLIdentifier } from '~/queries/utils'

export interface CompiledBuilderQuery {
    sql: string
    /** SELECT-order aliases per well — these are the response column names the visualization keys off */
    rowAliases: string[]
    columnAliases: string[]
    valueAliases: string[]
}

export class BuilderCompileError extends Error {}

const DATE_GRAIN_FUNCTIONS: Record<InsightBuilderDateGrain, string> = {
    // toStartOfHour keeps a time component (correct for hourly). Day uses toDate — not
    // toStartOfDay — so the bucket is a DATE, not a DateTime at midnight, which otherwise
    // renders as "00:00" on the axis. Week/month/quarter/year already return DATE.
    hour: 'toStartOfHour',
    day: 'toDate',
    week: 'toStartOfWeek',
    month: 'toStartOfMonth',
    quarter: 'toStartOfQuarter',
    year: 'toStartOfYear',
}

const SIMPLE_AGGREGATION_FUNCTIONS: Partial<Record<InsightBuilderAggregation, string>> = {
    sum: 'sum',
    avg: 'avg',
    min: 'min',
    max: 'max',
    count: 'count',
    count_distinct: 'countDistinct',
    median: 'median',
}

const QUANTILE_AGGREGATION_LEVELS: Partial<Record<InsightBuilderAggregation, number>> = {
    p90: 0.9,
    p95: 0.95,
    p99: 0.99,
}

// Aliases are emitted bare (never quoted) so response column names match them byte-for-byte;
// keywords must therefore be kept out of the alias namespace entirely.
const RESERVED_ALIASES = new Set([
    'all',
    'and',
    'anti',
    'any',
    'array',
    'as',
    'asc',
    'asof',
    'between',
    'both',
    'by',
    'case',
    'cast',
    'cross',
    'cube',
    'current',
    'date',
    'desc',
    'distinct',
    'else',
    'end',
    'extract',
    'final',
    'first',
    'following',
    'for',
    'format',
    'from',
    'full',
    'group',
    'having',
    'if',
    'ilike',
    'in',
    'inner',
    'interval',
    'is',
    'join',
    'last',
    'leading',
    'left',
    'like',
    'limit',
    'not',
    'null',
    'nulls',
    'offset',
    'on',
    'or',
    'order',
    'outer',
    'over',
    'partition',
    'preceding',
    'prewhere',
    'right',
    'rollup',
    'row',
    'rows',
    'sample',
    'select',
    'semi',
    'settings',
    'substring',
    'then',
    'ties',
    'to',
    'top',
    'totals',
    'trailing',
    'trim',
    'truncate',
    'unbounded',
    'union',
    'using',
    'when',
    'where',
    'window',
    'with',
])

export function dimensionExpr(dim: InsightBuilderDimension): string {
    const ref = escapePropertyAsHogQLIdentifier(dim.column)
    if (dim.dateGrain) {
        return `${DATE_GRAIN_FUNCTIONS[dim.dateGrain]}(${ref})`
    }
    // Fixed-width numeric bins: group each value into [floor(v/w)*w, +w). Width is numeric so
    // it's inlined directly (not a string literal). Non-positive widths are ignored.
    if (dim.numericBinWidth && dim.numericBinWidth > 0) {
        const w = dim.numericBinWidth
        return `floor(${ref} / ${w}) * ${w}`
    }
    return ref
}

export function measureExpr(measure: InsightBuilderMeasure): string {
    if (measure.column === '*') {
        if (measure.aggregation !== 'count') {
            throw new BuilderCompileError('Only count can aggregate across all rows')
        }
        return 'count()'
    }

    const ref = escapePropertyAsHogQLIdentifier(measure.column)

    const quantileLevel = QUANTILE_AGGREGATION_LEVELS[measure.aggregation]
    if (quantileLevel !== undefined) {
        return `quantile(${quantileLevel})(${ref})`
    }

    const fn = SIMPLE_AGGREGATION_FUNCTIONS[measure.aggregation]
    if (!fn) {
        throw new BuilderCompileError(`Unsupported aggregation: ${measure.aggregation}`)
    }
    return `${fn}(${ref})`
}

function escapeHogQLStringLiteral(value: string): string {
    return `'${value.replaceAll('\\', '\\\\').replaceAll("'", "\\'")}'`
}

function escapeLikePattern(value: string): string {
    // Escape LIKE wildcards so user text matches literally inside the %...% pattern
    return value.replaceAll('\\', '\\\\').replaceAll('%', '\\%').replaceAll('_', '\\_')
}

/** True when the filter has everything it needs to compile; incomplete filters are skipped. */
export function isFilterComplete(filter: InsightBuilderFilter): boolean {
    if (filter.operator === 'is_set' || filter.operator === 'is_not_set') {
        return true
    }
    return filter.value !== undefined && filter.value !== ''
}

export function filterExpr(filter: InsightBuilderFilter): string {
    const ref = escapePropertyAsHogQLIdentifier(filter.column)
    const value = filter.value ?? ''

    switch (filter.operator) {
        case 'eq':
            return `${ref} = ${escapeHogQLStringLiteral(value)}`
        case 'neq':
            return `${ref} != ${escapeHogQLStringLiteral(value)}`
        case 'gt':
            return `${ref} > ${escapeHogQLStringLiteral(value)}`
        case 'gte':
            return `${ref} >= ${escapeHogQLStringLiteral(value)}`
        case 'lt':
            return `${ref} < ${escapeHogQLStringLiteral(value)}`
        case 'lte':
            return `${ref} <= ${escapeHogQLStringLiteral(value)}`
        case 'contains':
            return `${ref} ILIKE ${escapeHogQLStringLiteral(`%${escapeLikePattern(value)}%`)}`
        case 'not_contains':
            return `${ref} NOT ILIKE ${escapeHogQLStringLiteral(`%${escapeLikePattern(value)}%`)}`
        case 'is_set':
            return `isNotNull(${ref})`
        case 'is_not_set':
            return `isNull(${ref})`
    }
}

export function sanitizeAlias(raw: string, taken: Set<string>): string {
    let base = raw
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, '_')
        .replace(/^_+|_+$/g, '')

    if (!base) {
        base = 'field'
    }
    if (/^[0-9]/.test(base)) {
        base = `_${base}`
    }
    if (RESERVED_ALIASES.has(base)) {
        base = `${base}_`
    }

    let candidate = base
    let suffix = 2
    while (taken.has(candidate)) {
        candidate = `${base}_${suffix}`
        suffix += 1
    }
    taken.add(candidate)
    return candidate
}

function dimensionAliasBase(dim: InsightBuilderDimension): string {
    if (dim.dateGrain) {
        return `${dim.column}_${dim.dateGrain}`
    }
    if (dim.numericBinWidth && dim.numericBinWidth > 0) {
        return `${dim.column}_binned`
    }
    return dim.column
}

function measureAliasBase(measure: InsightBuilderMeasure): string {
    if (measure.column === '*') {
        return 'count_rows'
    }
    return `${measure.aggregation}_${measure.column}`
}

function buildFromClause(config: InsightBuilderConfig): string {
    if (config.baseView) {
        return escapeDottedHogQLIdentifier(config.baseView)
    }

    const statements = splitQueries(config.baseQuery)
    if (statements.length === 0) {
        throw new BuilderCompileError('Write a base query in the Data tab first')
    }
    if (statements.length > 1) {
        throw new BuilderCompileError('Build mode needs a single SELECT statement as its base')
    }
    return `(\n${statements[0].query}\n)`
}

/** True when the base can serve as the builder's FROM clause: exactly one statement. */
export function isCompilableBase(baseQuery: string): boolean {
    return splitQueries(baseQuery).length === 1
}

const SELECT_ALL_TARGET_REGEX =
    /^\s*SELECT\s+\*\s+FROM\s+(`(?:[^`]|``)+`|"[^"]+"|[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\s*(?:LIMIT\s+\d+)?\s*;?\s*$/i

/**
 * When the base is a bare `SELECT * FROM <object> [LIMIT n]`, return the (unquoted) object name.
 * The builder then compiles FROM the object directly, dropping the preview LIMIT so aggregates
 * cover the full table/view rather than the previewed sample.
 */
export function detectSelectAllTarget(baseQuery: string): string | null {
    const match = SELECT_ALL_TARGET_REGEX.exec(baseQuery)
    if (!match) {
        return null
    }
    const raw = match[1]
    if (raw.startsWith('`')) {
        return raw.slice(1, -1).replaceAll('``', '`')
    }
    if (raw.startsWith('"')) {
        return raw.slice(1, -1)
    }
    return raw
}

export function compileBuilderQuery(config: InsightBuilderConfig): CompiledBuilderQuery {
    if (config.rows.length + config.columns.length + config.values.length === 0) {
        throw new BuilderCompileError('Add at least one field to Rows, Columns, or Values')
    }

    const taken = new Set<string>()
    const rowParts = config.rows.map((dim) => ({
        expr: dimensionExpr(dim),
        alias: sanitizeAlias(dimensionAliasBase(dim), taken),
    }))
    const columnParts = config.columns.map((dim) => ({
        expr: dimensionExpr(dim),
        alias: sanitizeAlias(dimensionAliasBase(dim), taken),
    }))
    const valueParts = config.values.map((measure) => ({
        expr: measureExpr(measure),
        alias: sanitizeAlias(measureAliasBase(measure), taken),
    }))

    // Columns (the x-axis) come first so the x-axis is always the first response column, in a
    // stable position whether or not a Rows breakdown is present — chart heuristics key off it.
    const selectList = [...columnParts, ...rowParts, ...valueParts]
        .map((part) => `    ${part.expr} AS ${part.alias}`)
        .join(',\n')
    const dimensionExprs = [...columnParts, ...rowParts].map((part) => part.expr)

    const lines = [`SELECT\n${selectList}`, `FROM ${buildFromClause(config)}`]
    const filterExprs = (config.filters ?? []).filter(isFilterComplete).map(filterExpr)
    if (filterExprs.length > 0) {
        lines.push(`WHERE ${filterExprs.join(' AND ')}`)
    }
    if (dimensionExprs.length > 0) {
        lines.push(`GROUP BY ${dimensionExprs.join(', ')}`)
    }
    // Charts consume rows in response order; sort by the x-axis (Columns) so cartesian charts
    // render left-to-right, falling back to the Rows breakdown when there's no x-axis
    const orderAlias = columnParts[0]?.alias ?? rowParts[0]?.alias
    if (orderAlias) {
        lines.push(`ORDER BY ${orderAlias} ASC`)
    }

    return {
        sql: lines.join('\n'),
        rowAliases: rowParts.map((part) => part.alias),
        columnAliases: columnParts.map((part) => part.alias),
        valueAliases: valueParts.map((part) => part.alias),
    }
}
