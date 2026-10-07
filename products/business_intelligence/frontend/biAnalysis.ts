import { BIConfig, BIField, BITableCalculation, BIValue } from '~/queries/schema/schema-business-intelligence'
import { escapeHogQLString, escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { biComparisonCategory } from './biComparison'
import { limitBIComparisonQuery } from './biComparisonLimit'
import { buildBIFilledPeriod, getBIMissingDatesDisabledReason } from './biTimeSeries'

export const BI_TABLE_CALCULATIONS: { value: BITableCalculation['type']; label: string }[] = [
    { value: 'percent_of_total', label: 'Percent of total' },
    { value: 'running_total', label: 'Running total' },
    { value: 'difference', label: 'Change from previous point' },
    { value: 'percent_change', label: 'Percent change from previous point' },
    { value: 'moving_average', label: 'Moving average' },
    { value: 'rank', label: 'Rank' },
]

export function isBITableCalculation(value: unknown): value is BITableCalculation {
    if (!value || typeof value !== 'object') {
        return false
    }
    const candidate = value as BITableCalculation
    return (
        BI_TABLE_CALCULATIONS.some(({ value }) => value === candidate.type) &&
        (candidate.computeUsing === undefined || typeof candidate.computeUsing === 'string') &&
        (candidate.requireFullWindow === undefined || typeof candidate.requireFullWindow === 'boolean') &&
        (candidate.window === undefined ||
            (Number.isInteger(candidate.window) && candidate.window >= 1 && candidate.window <= 1000))
    )
}

export function isBIAnalysisConfig(config: Partial<BIConfig>): boolean {
    const top = config.topN
    const totals = config.totals
    return (
        (config.missingDates === undefined || ['gap', 'zero'].includes(config.missingDates)) &&
        (top === undefined ||
            (!!top &&
                typeof top === 'object' &&
                typeof top.fieldId === 'string' &&
                Number.isInteger(top.count) &&
                top.count >= 1 &&
                top.count <= 100 &&
                Number.isInteger(top.measureIndex) &&
                top.measureIndex >= 0 &&
                typeof top.includeOther === 'boolean')) &&
        (totals === undefined ||
            (!!totals &&
                typeof totals === 'object' &&
                [totals.rows, totals.columns, totals.subtotals].every(
                    (value) => value === undefined || typeof value === 'boolean'
                )))
    )
}

export interface BIAnalysisDimension {
    field: BIField
    alias: string
    expression: string
}

export interface BIAnalysisMeasure {
    value?: BIValue
    alias: string
    expression: string
}

export interface BIAnalysisInput {
    rows: BIAnalysisDimension[]
    columns: BIAnalysisDimension[]
    measures: BIAnalysisMeasure[]
    from: string
    where: string
    orderBy: string | null
    resultLimit?: number
    resultWhere?: string | null
    previousWhere?: string
    previousDimensions?: string[]
}

export function hasBIAnalysis(config: BIConfig): boolean {
    return (
        config.chartType === ChartDisplayType.TwoDimensionalHeatmap ||
        (!!config.missingDates && !getBIMissingDatesDisabledReason(config)) ||
        !!config.topN ||
        !!config.resultFilters?.length ||
        config.values.some((value) => !!value.tableCalculation) ||
        !!(config.totals?.rows || config.totals?.columns || config.totals?.subtotals)
    )
}

function calculationExpression(
    measure: BIAnalysisMeasure,
    dimensions: BIAnalysisDimension[],
    partition: string[]
): string {
    const column = escapeRawPropertyAsHogQLIdentifier(measure.alias)
    const calc = measure.value?.tableCalculation
    if (!calc) {
        return column
    }
    const axis =
        dimensions.find((dimension) => dimension.field.id === calc.computeUsing) ??
        dimensions.find((dimension) => ['date', 'datetime'].includes(dimension.field.type)) ??
        dimensions[0]
    const across = calc.computeUsing === 'table' ? dimensions : axis ? [axis] : []
    const within = [
        ...partition,
        ...dimensions.filter((dimension) => !across.includes(dimension)).map((dimension) => dimension.alias),
    ]
    const partitionBy = within.length ? `PARTITION BY ${within.join(', ')} ` : ''
    const order = across.length ? across.map((dimension) => `${dimension.alias} ASC`).join(', ') : column
    const window = `${partitionBy}ORDER BY ${order}`
    const previous = `lag(${column}, 1, NULL) OVER (${window})`
    switch (calc.type) {
        case 'percent_of_total':
            return `${column} * 1.0 / nullIf(sum(${column}) OVER (${partitionBy.trim()}), 0)`
        case 'running_total':
            return `sum(${column}) OVER (${window} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`
        case 'difference':
            return `${column} - ${previous}`
        case 'percent_change':
            return `(${column} - ${previous}) * 1.0 / nullIf(abs(${previous}), 0)`
        case 'moving_average': {
            const size = Math.max(1, Math.min(1000, Math.trunc(calc.window ?? 3)))
            const frame = `${window} ROWS BETWEEN ${size - 1} PRECEDING AND CURRENT ROW`
            const average = `avg(${column}) OVER (${frame})`
            return `if(count(${column}) OVER (${frame}) ${calc.requireFullWindow ? `= ${size}` : '> 0'}, ${average}, NULL)`
        }
        case 'rank':
            return `rank() OVER (${partitionBy}ORDER BY ${column} DESC)`
    }
}

function groupingSets(config: BIConfig, input: BIAnalysisInput): string[][] {
    const rows = input.rows.map((dimension) => dimension.alias)
    const columns = input.columns.map((dimension) => dimension.alias)
    const sets = [[...rows, ...columns]]
    if (![ChartDisplayType.ActionsTable, ChartDisplayType.TwoDimensionalHeatmap].includes(config.chartType)) {
        return sets
    }
    const pivot = config.chartType === ChartDisplayType.TwoDimensionalHeatmap
    if (pivot && config.totals?.rows) {
        sets.push(rows)
    }
    if (pivot && config.totals?.columns) {
        sets.push(columns)
    }
    if (config.totals?.rows || config.totals?.columns) {
        sets.push([])
    }
    if (config.totals?.subtotals) {
        for (let length = 1; length < rows.length; length++) {
            sets.push([...rows.slice(0, length), ...columns])
        }
        for (let length = 1; length < columns.length; length++) {
            sets.push([...rows, ...columns.slice(0, length)])
        }
    }
    if (pivot) {
        // Reaggregate every hierarchy intersection: averages and distinct counts cannot be summed from leaves.
        for (let rowDepth = 1; rowDepth <= rows.length; rowDepth++) {
            for (let columnDepth = 1; columnDepth <= columns.length; columnDepth++) {
                sets.push([...rows.slice(0, rowDepth), ...columns.slice(0, columnDepth)])
            }
            if (config.totals?.rows) {
                sets.push(rows.slice(0, rowDepth))
            }
        }
        if (config.totals?.columns) {
            for (let depth = 1; depth <= columns.length; depth++) {
                sets.push(columns.slice(0, depth))
            }
        }
    }
    return [...new Map(sets.map((set) => [JSON.stringify(set), set])).values()]
}

export function buildBIAnalysisQuery(config: BIConfig, input: BIAnalysisInput): string {
    const dimensions = [...input.rows, ...input.columns]
    const pivot = config.chartType === ChartDisplayType.TwoDimensionalHeatmap
    const ctes: string[] = []
    const topMeasure = config.values.length
        ? input.measures.find((measure) => measure.value === config.values[config.topN?.measureIndex ?? 0])
        : input.measures[0]
    const topDimension = topMeasure && dimensions.find((dimension) => dimension.field.id === config.topN?.fieldId)
    if (config.topN && topDimension && topMeasure) {
        ctes.push(
            `bi_top AS (SELECT ${topDimension.expression} AS bi_key FROM ${input.from} WHERE ${input.where} GROUP BY bi_key ORDER BY ${topMeasure.expression} DESC, bi_key ASC LIMIT ${Math.max(1, Math.min(100, Math.trunc(config.topN.count)))})`
        )
    }
    const sets = groupingSets(config, input)
    const totals = sets.length > 1
    const aliases = dimensions.map((dimension) => dimension.alias)
    const groupingFlags = dimensions.map((_, index) => `bi_grouping_${index}`)
    const periods = input.previousWhere ? [false, true] : [false]
    const topMember = topDimension
        ? `(${topDimension.expression} IN (SELECT bi_key FROM bi_top) OR (${topDimension.expression} IS NULL AND (SELECT count(*) FROM bi_top WHERE bi_key IS NULL) > 0))`
        : ''
    for (const previous of periods) {
        const expressions = dimensions.map((dimension, index) => {
            let expression = previous ? input.previousDimensions![index] : dimension.expression
            if (config.topN && dimension === topDimension && config.topN.includeOther) {
                // A tagged array keeps an actual category named "Other" distinct from the remainder.
                expression = `if(${topMember}, ['0', toString(${expression})], ['1', 'Other'])`
            }
            return expression
        })
        const where = previous ? input.previousWhere! : input.where
        const topFilter = config.topN && topDimension && !config.topN.includeOther ? ` AND ${topMember}` : ''
        const select = [
            ...expressions.map((expression, index) => `${expression} AS ${aliases[index]}`),
            ...input.measures.map(
                (measure) => `${measure.expression} AS ${escapeRawPropertyAsHogQLIdentifier(measure.alias)}`
            ),
            ...(totals
                ? [
                      `grouping(${expressions.join(', ')}) AS bi_grouping`,
                      ...expressions.map((expression, index) => `grouping(${expression}) AS ${groupingFlags[index]}`),
                  ]
                : []),
        ]
        ctes.push(
            `bi_${previous ? 'previous' : 'current'} AS (SELECT ${select.join(', ')} FROM ${input.from} WHERE ${where}${topFilter}${dimensions.length ? ` GROUP BY ${totals ? `GROUPING SETS (${sets.map((set) => `(${set.join(', ')})`).join(', ')})` : aliases.join(', ')}` : ''})`
        )
        const filled = buildBIFilledPeriod(config, input, previous, totals)
        if (filled) {
            ctes.push(filled)
        }
    }
    const calculations = input.measures.map((measure) => {
        const expression = calculationExpression(measure, dimensions, totals ? ['bi_grouping'] : [])
        return `${totals && measure.value?.tableCalculation ? `if(bi_grouping = 0, ${expression}, NULL)` : expression} AS ${escapeRawPropertyAsHogQLIdentifier(measure.alias)}`
    })
    const comparisonLabel = config.compareFilter?.compare_to ? 'Comparison period' : 'Previous period'
    const periodQuery = (previous: boolean): string =>
        `SELECT ${[...aliases, ...calculations, ...(totals ? ['bi_grouping', ...groupingFlags] : []), ...(input.previousWhere ? [`${escapeHogQLString(previous ? comparisonLabel : 'Current period')} AS bi_period`] : [])].join(', ')} FROM bi_${previous ? 'previous' : 'current'}${config.missingDates && !getBIMissingDatesDisabledReason(config) ? '_filled' : ''}`
    ctes.push(`bi_calculated AS (${periods.map(periodQuery).join(' UNION ALL ')})`)
    const results = input.resultWhere ? 'bi_filtered' : 'bi_calculated'
    if (input.resultWhere) {
        ctes.push(
            `bi_filtered AS (SELECT * FROM bi_calculated WHERE ${totals ? 'bi_grouping != 0 OR ' : ''}(${input.resultWhere}))`
        )
    }
    const displayedDimension = (dimension: BIAnalysisDimension, index: number): string => {
        let expression = dimension.alias
        if (dimension === topDimension && config.topN?.includeOther) {
            expression = `if(${expression}[1] = '1', 'Other', if(startsWith(${expression}[2], 'Other'), concat(${expression}[2], ' (category)'), ${expression}[2]))`
        }
        const label =
            totals || pivot || config.totals?.subtotals
                ? `if(startsWith(toString(${expression}), 'Total'), concat(toString(${expression}), ' (category)'), toString(${expression}))`
                : expression
        return totals ? `if(${groupingFlags[index]} != 0, 'Total', ${label})` : label
    }
    const displayed = dimensions.map(displayedDimension)
    const axis = (side: 'rows' | 'columns'): string[] => {
        const fields = input[side]
        if (!fields.length) {
            return []
        }
        const expressions = fields.map((field) => displayed[dimensions.indexOf(field)])
        return [
            `${expressions.length === 1 ? expressions[0] : `toJSONString(tuple(${expressions.join(', ')}))`} AS ${fields.length === 1 ? fields[0].alias : `bi_${side}`}`,
        ]
    }
    const select = [
        ...(pivot
            ? [...axis('rows'), ...axis('columns')]
            : dimensions.map((dimension, index) => `${displayed[index]} AS ${dimension.alias}`)),
        ...input.measures.map((measure) => escapeRawPropertyAsHogQLIdentifier(measure.alias)),
    ]
    if (input.previousWhere) {
        const xDimension =
            dimensions.find((dimension) => ['date', 'datetime'].includes(dimension.field.type)) ??
            input.columns[0] ??
            input.rows[0]
        const breakdown = dimensions.find((dimension) => dimension !== xDimension)
        select.push(
            `${breakdown ? `concat(bi_period, ' · ', ${biComparisonCategory(displayed[dimensions.indexOf(breakdown)])})` : 'bi_period'} AS bi_comparison`
        )
    }
    let order = input.orderBy
    for (const dimension of dimensions) {
        if (order === `${dimension.expression} ASC` || order === `${dimension.expression} DESC`) {
            order = `${dimension.alias} ${order.endsWith(' ASC') ? 'ASC' : 'DESC'}`
        }
    }
    if (input.previousWhere) {
        const query = `WITH ${ctes.join(',\n')} SELECT ${[...select, ...(totals ? ['bi_grouping AS bi_comparison_grouping'] : [])].join(', ')} FROM ${results}`
        return limitBIComparisonQuery({
            query,
            config,
            columns: [...aliases, ...input.measures.map(({ alias }) => alias), 'bi_comparison'],
            dimensions: aliases,
            order,
            probe: (input.resultLimit ?? config.limit) > config.limit,
            grouping: totals ? 'bi_comparison_grouping' : undefined,
        })
    }
    if (totals) {
        // Reserve at least half the result budget for detail cells when summaries alone exceed it.
        ctes.push(
            `bi_ranked AS (SELECT *, row_number() OVER (PARTITION BY bi_grouping = 0 ORDER BY bi_grouping DESC${order ? `, ${order}` : ''}) AS bi_rank FROM ${results})`
        )
    }
    for (const { alias } of dimensions) {
        if (order === `${alias} ASC` || order === `${alias} DESC`) {
            order = `bi_result.${order}`
            break
        }
    }
    return `WITH ${ctes.join(',\n')}\nSELECT ${select.join(', ')} FROM ${totals ? 'bi_ranked' : results} AS bi_result${totals ? ` WHERE bi_grouping = 0 OR bi_rank <= ${Math.floor(config.limit / 2)}` : ''}${totals || order ? ` ORDER BY ${[...(totals ? ['bi_grouping DESC'] : []), ...(order ? [order] : [])].join(', ')}` : ''} LIMIT ${input.resultLimit ?? config.limit}`
}
