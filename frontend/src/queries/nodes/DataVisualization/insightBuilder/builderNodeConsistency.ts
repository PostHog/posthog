import { DataVisualizationNode, InsightBuilderConfig } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { effectiveWells } from './chartCapabilities'
import { CompiledBuilderQuery, compileBuilderQuery } from './compileBuilderQuery'

/**
 * Compile a builder config exactly the way applyWells does for a given chart type: only the
 * wells the chart can express participate (extras stay stashed in the config). Throws
 * BuilderCompileError for unusable configs, like compileBuilderQuery.
 */
export function compileNodeBuilder(
    builder: InsightBuilderConfig,
    display: DataVisualizationNode['display']
): CompiledBuilderQuery {
    const effectiveDisplay = display && display !== ChartDisplayType.Auto ? display : ChartDisplayType.ActionsTable
    const effective = effectiveWells(
        { rows: builder.rows, columns: builder.columns, values: builder.values },
        effectiveDisplay
    )
    return compileBuilderQuery({
        ...builder,
        rows: effective.rows,
        columns: effective.columns,
        values: effective.values,
    })
}

// Whitespace-insensitive comparison: formatting-only changes to the compiler must not flag every
// previously saved insight as edited. Structural drift (different fields, functions, clauses)
// still mismatches. Whitespace inside string literals is collapsed too — an acceptable false
// match, since the consequence is just hydrating as normal.
function normalizeSql(sql: string): string {
    return sql
        .replace(/\s+/g, ' ')
        .replace(/\s*([(),])\s*/g, '$1')
        .trim()
}

/**
 * Whether a saved node's builder config still describes its SQL. The builder keeps the two in
 * lockstep, so a mismatch means the SQL was edited outside the builder (e.g. in the plain SQL
 * editor while the builder flag was off) — hydrating the wells then would silently regenerate
 * SQL from a config the query no longer matches. Callers drop the stale config instead: the SQL
 * wins, and the insight behaves like a classic SQL insight until it is rebuilt.
 */
export function builderConfigMatchesQuery(node: DataVisualizationNode): boolean {
    const builder = node.builder
    if (!builder?.enabled) {
        return true
    }
    // The saved compile snapshot is the reliable signal: comparing against it survives compiler
    // output changes between releases, which recompiling cannot (any drift would misread every
    // older insight as externally edited and silently degrade it to classic).
    if (builder.compiledQuery) {
        return normalizeSql(builder.compiledQuery) === normalizeSql(node.source.query)
    }
    // Configs saved before compiledQuery existed: recompile and compare
    try {
        const compiled = compileNodeBuilder(builder, node.display)
        return normalizeSql(compiled.sql) === normalizeSql(node.source.query)
    } catch {
        return false
    }
}
