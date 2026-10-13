import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

export type BillingUsageInterval = 'day' | 'week' | 'month'

export function supportsUsageAggregation(query: unknown): query is DataVisualizationNode {
    const node = query as DataVisualizationNode | null
    return (
        node?.kind === NodeKind.DataVisualizationNode &&
        node.source.kind === NodeKind.HogQLQuery &&
        !node.source.connectionId &&
        !node.chartSettings?.seriesBreakdownColumn &&
        !!node.chartSettings?.xAxis?.column &&
        !!node.chartSettings?.yAxis?.length
    )
}

export function billingUsageQuery(query: DataVisualizationNode, interval: BillingUsageInterval): DataVisualizationNode {
    if (!supportsUsageAggregation(query)) {
        return query
    }
    const dateColumn = escapeRawPropertyAsHogQLIdentifier(query.chartSettings!.xAxis!.column)
    const valueColumns = [...new Set(query.chartSettings!.yAxis!.map(({ column }) => column))].map(
        escapeRawPropertyAsHogQLIdentifier
    )
    const source = query.source.query.trim().replace(/;$/, '')
    const bucket = {
        day: `usage.${dateColumn}`,
        week: `toStartOfWeek(usage.${dateColumn}, 1)`,
        month: `toStartOfMonth(usage.${dateColumn})`,
    }[interval]
    const select = [
        `${bucket} AS ${dateColumn}`,
        ...valueColumns.map((column) => `sum(usage.${column}) AS ${column}`),
    ].join(',\n    ')

    return {
        ...query,
        display: query.display === ChartDisplayType.Auto ? ChartDisplayType.ActionsLineGraph : query.display,
        source: {
            ...query.source,
            // An explicit limit avoids the SQL table paginator truncating long daily ranges.
            query: `SELECT\n    ${select}\nFROM (\n${source}\n) AS usage\nGROUP BY ${dateColumn}\nORDER BY ${dateColumn}\nLIMIT 10000`,
        },
    }
}
