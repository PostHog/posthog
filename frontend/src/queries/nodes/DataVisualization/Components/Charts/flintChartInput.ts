import type { ChartAssemblyInput } from 'flint-chart/core'

export interface FlintChartInputArgs {
    columns: string[]
    /** ClickHouse type per column (from the HogQL response `types` tuples), when available. */
    columnTypes: (string | null)[]
    rows: unknown[][]
    /** Flint chart type override; omit to infer one from the result shape. */
    chartType?: string | null
}

type ColumnClass = 'temporal' | 'numeric' | 'categorical'

const CLASS_TO_SEMANTIC_TYPE: Record<ColumnClass, string> = {
    temporal: 'Date',
    numeric: 'Quantity',
    categorical: 'Category',
}

function classifyByClickhouseType(chType: string | null): ColumnClass | null {
    if (!chType) {
        return null
    }
    if (/Date/i.test(chType)) {
        return 'temporal'
    }
    if (/Int|Float|Decimal/i.test(chType)) {
        return 'numeric'
    }
    return 'categorical'
}

function classifyBySample(values: unknown[]): ColumnClass {
    const sample = values.find((v) => v != null)
    if (typeof sample === 'number') {
        return 'numeric'
    }
    if (typeof sample === 'string' && /^\d{4}-\d{2}-\d{2}/.test(sample)) {
        return 'temporal'
    }
    return 'categorical'
}

/**
 * Build a Flint `ChartAssemblyInput` from raw SQL-editor results.
 *
 * Column roles come from the ClickHouse column types (falling back to value
 * sniffing): the first temporal column becomes the x-axis (else the first
 * categorical one), numeric columns become measures, and a leftover
 * categorical column becomes the series split. Flint's compiler derives
 * everything else — sort order, zero baseline, formatting, overflow.
 */
export function flintChartInput({
    columns,
    columnTypes,
    rows,
    chartType,
}: FlintChartInputArgs): ChartAssemblyInput | null {
    if (columns.length === 0 || rows.length === 0) {
        return null
    }

    const values = rows.map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i]])))
    const classes: ColumnClass[] = columns.map(
        (_, i) => classifyByClickhouseType(columnTypes[i] ?? null) ?? classifyBySample(rows.map((r) => r[i]))
    )
    const byClass = (cls: ColumnClass): string[] => columns.filter((_, i) => classes[i] === cls)
    const temporal = byClass('temporal')
    const numeric = byClass('numeric')
    const categorical = byClass('categorical')

    const semanticTypes = Object.fromEntries(columns.map((c, i) => [c, CLASS_TO_SEMANTIC_TYPE[classes[i]]]))
    const resolvedChartType = chartType ?? (temporal.length > 0 && numeric.length > 0 ? 'Line Chart' : 'Bar Chart')

    let encodings: ChartAssemblyInput['chart_spec']['encodings']
    if (resolvedChartType === 'Pie Chart' || resolvedChartType === 'Doughnut Chart') {
        const sliceField = categorical[0] ?? temporal[0] ?? columns[0]
        const sizeField = numeric[0]
        encodings = sizeField
            ? { color: { field: sliceField }, size: { field: sizeField } }
            : { color: { field: sliceField } }
    } else {
        const x = temporal[0] ?? categorical[0] ?? columns[0]
        const measures = numeric.filter((c) => c !== x)
        const seriesField = categorical.find((c) => c !== x)
        if (measures.length === 0) {
            // No measure columns: chart row counts per x value
            encodings = { x: { field: x }, y: { aggregate: 'count' } }
        } else if (measures.length === 1) {
            encodings = {
                x: { field: x },
                y: { field: measures[0] },
                ...(seriesField ? { color: { field: seriesField } } : {}),
            }
        } else {
            // Multiple measures fold into static series (one line/bar group per column)
            encodings = { x: { field: x }, y: measures.map((field) => ({ field })) }
        }
    }

    return {
        data: { values },
        semantic_types: semanticTypes,
        chart_spec: { chartType: resolvedChartType, encodings },
    }
}
