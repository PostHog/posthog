import { DataWarehouseNode, MarketingAnalyticsConstants, NodeKind } from '~/queries/schema/schema-general'
import { HogQLMathType } from '~/types'

import { ExternalTable } from './marketingAnalyticsLogic'
import { safeFloat, sumSafeFloat, validColumnsForTiles } from './utils'

/** Mirrors backend _is_simple_column_name: only allows alphanumeric, underscores, and dots */
function isSimpleColumnName(value: string): boolean {
    return /^[a-zA-Z0-9_][a-zA-Z0-9_.]*[a-zA-Z0-9_]$|^[a-zA-Z0-9_]$/.test(value)
}

function sanitizeColumnName(value: string): string | null {
    return isSimpleColumnName(value) ? value : null
}

function sanitizeCurrencyCode(value: string): string | null {
    return /^[A-Z]{3}$/.test(value) ? value : null
}

/** Build a HogQL expression for the currency value (constant string or column reference) */
function buildCurrencyExpr(currencyField: string | undefined, baseCurrency: string): string {
    const safeFallback = `'${sanitizeCurrencyCode(baseCurrency) ?? 'USD'}'`
    if (!currencyField) {
        return safeFallback
    }
    if (currencyField.startsWith(MarketingAnalyticsConstants.ConstantValuePrefix)) {
        const code = currencyField.slice(MarketingAnalyticsConstants.ConstantValuePrefix.length)
        return `'${sanitizeCurrencyCode(code) ?? 'USD'}'`
    }
    // Backwards compatibility: bare ISO currency codes (e.g. "USD") saved before
    // the "const:" prefix was enforced by the frontend are treated as constants.
    const maybeCode = sanitizeCurrencyCode(currencyField)
    if (maybeCode) {
        return `'${maybeCode}'`
    }
    return sanitizeColumnName(currencyField) ?? safeFallback
}

/** Build a HogQL date expression for currency conversion lookup */
function buildDateExpr(table: ExternalTable): string {
    if (table.dw_source_type === 'self-managed') {
        return 'today()'
    }
    const dateCol = sanitizeColumnName(table.source_map!.date!)
    if (!dateCol) {
        return 'today()'
    }
    return `coalesce(toString(${dateCol}), '1970-01-01')`
}

export const externalAdsCostTile = (
    table: ExternalTable,
    baseCurrency: string,
    tileColumnSelection: validColumnsForTiles
): DataWarehouseNode | null => {
    if (!table.source_map || !table.source_map.date || !table.source_map.cost) {
        return null
    }

    let mathHogql: string

    if (tileColumnSelection === 'roas') {
        const costColumn = sanitizeColumnName(table.source_map.cost)
        const conversionValueColumn = table.source_map.reported_conversion_value
            ? sanitizeColumnName(table.source_map.reported_conversion_value)
            : null
        if (!costColumn || !conversionValueColumn) {
            return null
        }
        mathHogql = `${sumSafeFloat(conversionValueColumn)} / nullIf(SUM(toFloat(${costColumn})), 0)`
    } else {
        const rawColumn = table.source_map[tileColumnSelection]
        const column = rawColumn ? sanitizeColumnName(rawColumn) : null
        if (!column) {
            return null
        }
        const currencyExpr = buildCurrencyExpr(table.source_map.currency, baseCurrency)
        const dateExpr = buildDateExpr(table)
        const safeCurrency = sanitizeCurrencyCode(baseCurrency) ?? 'USD'
        mathHogql = `SUM(convertCurrency(${currencyExpr}, '${safeCurrency}', ${safeFloat(column)}, _toDate(${dateExpr})))`
    }

    const dateField = sanitizeColumnName(table.source_map.date)
    if (!dateField) {
        return null
    }

    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: table.schema_name,
        custom_name: `${table.schema_name} ${tileColumnSelection}`,
        id_field: 'id',
        distinct_id_field: 'id',
        timestamp_field: dateField,
        table_name: table.name,
        dw_source_type: table.dw_source_type,
        math: HogQLMathType.HogQL,
        math_hogql: mathHogql,
    }
}
