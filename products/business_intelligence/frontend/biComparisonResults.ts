import { BIConfig } from '~/queries/schema/schema-business-intelligence'

import { getBIResultDimensions } from './biEditorTypes'
import { biNumericValue } from './biResultPresentation'

export interface BIComparisonRow {
    key: string
    dimensions: unknown[]
    current?: Record<string, unknown>
    previous?: Record<string, unknown>
}

export function buildBIComparisonRows(config: BIConfig, columns: string[], results: unknown[][]): BIComparisonRow[] {
    const dimensions = getBIResultDimensions(config)
    const groups = new Map<string, BIComparisonRow>()
    for (const result of results) {
        const record = Object.fromEntries(columns.map((column, index) => [column, result[index]]))
        const values = dimensions.map(({ column }) => record[column])
        const key = JSON.stringify(values)
        const row = groups.get(key) ?? { key, dimensions: values }
        if (/^(Previous|Comparison) period(?: · |$)/.test(String(record.bi_comparison))) {
            row.previous = record
        } else {
            row.current = record
        }
        groups.set(key, row)
    }
    return [...groups.values()]
}

export function getBIComparisonValues(
    row: BIComparisonRow,
    column: string
): { current: number | null; previous: number | null; change: number | null; percent: number | null } {
    const current = biNumericValue(row.current?.[column])
    const previous = biNumericValue(row.previous?.[column])
    const change = current === null || previous === null ? null : current - previous
    return {
        current,
        previous,
        change,
        percent: change === null || previous === null || previous === 0 ? null : change / Math.abs(previous),
    }
}
