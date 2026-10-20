import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'

export function getBIComparisonGroupLimit(config: BIConfig): number {
    // Keep room for both periods without exceeding the backend's row cap.
    return Math.floor(config.limit / 2)
}

export function limitBIComparisonQuery({
    query,
    config,
    columns,
    dimensions,
    order,
    probe,
    grouping,
}: {
    query: string
    config: BIConfig
    columns: string[]
    dimensions: string[]
    order: string | null
    probe: boolean
    grouping?: string
}): string {
    const keys = dimensions.map(escapeRawPropertyAsHogQLIdentifier)
    const partition = keys.length ? `PARTITION BY ${keys.join(', ')}` : ''
    const sort = order?.match(/^(.*) (ASC|DESC)$/)
    const score = sort
        ? `coalesce(max(if(substring(bi_comparison, 1, 14) = 'Current period', ${sort[1]}, NULL)) OVER (${partition}), max(${sort[1]}) OVER (${partition}))`
        : '1'
    const ranking = [
        ...(grouping ? [`${grouping} DESC`] : []),
        `bi_comparison_sort ${sort?.[2] ?? 'ASC'}`,
        ...keys.map((key) => `${key} ASC`),
    ].join(', ')
    const ctes = [
        `bi_comparison_data AS (${query})`,
        `bi_comparison_scored AS (SELECT *, ${score} AS bi_comparison_sort FROM bi_comparison_data)`,
    ]
    const groupLimit = getBIComparisonGroupLimit(config)
    if (grouping) {
        ctes.push(
            `bi_comparison_summaries AS (SELECT *, dense_rank() OVER (PARTITION BY ${grouping} = 0 ORDER BY ${ranking}) AS bi_summary_rank FROM bi_comparison_scored)`,
            `bi_comparison_budget AS (SELECT * FROM bi_comparison_summaries WHERE ${grouping} = 0 OR bi_summary_rank <= ${Math.floor(groupLimit / 2)})`
        )
    }
    ctes.push(
        `bi_comparison_ranked AS (SELECT *, dense_rank() OVER (ORDER BY ${ranking}) AS bi_comparison_rank FROM ${grouping ? 'bi_comparison_budget' : 'bi_comparison_scored'})`
    )
    const requestedGroups = groupLimit + (probe ? 1 : 0)
    return `WITH ${ctes.join(',\n')} SELECT ${columns.map(escapeRawPropertyAsHogQLIdentifier).join(', ')} FROM bi_comparison_ranked WHERE bi_comparison_rank <= ${requestedGroups} ORDER BY bi_comparison_rank ASC, bi_comparison ASC LIMIT ${requestedGroups * 2}`
}
