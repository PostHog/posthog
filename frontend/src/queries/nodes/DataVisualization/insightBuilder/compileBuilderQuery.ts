import { splitQueries } from 'scenes/data-warehouse/editor/multiQueryUtils'

import {
    InsightBuilderAggregation,
    InsightBuilderConfig,
    InsightBuilderDateGrain,
    InsightBuilderDimension,
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
    hour: 'toStartOfHour',
    day: 'toStartOfDay',
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
    return dim.dateGrain ? `${DATE_GRAIN_FUNCTIONS[dim.dateGrain]}(${ref})` : ref
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
    return dim.dateGrain ? `${dim.column}_${dim.dateGrain}` : dim.column
}

function measureAliasBase(measure: InsightBuilderMeasure): string {
    if (measure.column === '*') {
        return 'count_star'
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

    const selectList = [...rowParts, ...columnParts, ...valueParts]
        .map((part) => `    ${part.expr} AS ${part.alias}`)
        .join(',\n')
    const dimensionExprs = [...rowParts, ...columnParts].map((part) => part.expr)

    const lines = [`SELECT\n${selectList}`, `FROM ${buildFromClause(config)}`]
    if (dimensionExprs.length > 0) {
        lines.push(`GROUP BY ${dimensionExprs.join(', ')}`)
    }
    // Charts consume rows in response order, so dimension ordering is part of the contract
    const orderAlias = rowParts[0]?.alias ?? columnParts[0]?.alias
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
