import { deepEqual } from 'fast-equals'

import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { DataCatalogMetricApi } from 'products/data_catalog/frontend/generated/api.schemas'

import { getBIComparisonGroupLimit } from './biComparisonLimit'
import { DEFAULT_BI_CONFIG } from './biEditorTypes'

export function catalogMetricWorksheet(
    metric: Pick<DataCatalogMetricApi, 'name' | 'definition'>
): BIVisualizationNode | null {
    const definition = metric.definition
    if (definition?.kind !== NodeKind.HogQLQuery || typeof definition.query !== 'string') {
        return null
    }
    const source: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: definition.query,
        ...(definition.values ? { values: definition.values as HogQLQuery['values'] } : {}),
    }
    return {
        kind: NodeKind.BIVisualizationNode,
        source,
        display: ChartDisplayType.ActionsTable,
        config: {
            ...DEFAULT_BI_CONFIG,
            chartType: ChartDisplayType.ActionsTable,
            querySnapshot: source,
            catalogMetric: metric.name,
        },
    }
}

export function getBIMetricSnapshot(
    worksheet: BIVisualizationNode,
    lastRun: BIVisualizationNode | null,
    response: unknown,
    ready: boolean
): string | null {
    if (
        !ready ||
        !deepEqual(worksheet.source, lastRun?.source) ||
        !response ||
        typeof response !== 'object' ||
        !('hogql' in response) ||
        typeof response.hogql !== 'string'
    ) {
        return null
    }
    if (worksheet.config.compareFilter?.compare && !worksheet.config.querySnapshot) {
        // Only rewrite our generated outer clause: a row LIMIT can split a comparison group.
        const probeClause =
            /(FROM\s+bi_comparison_ranked\s+WHERE\s+lessOrEquals\(bi_comparison_rank,\s*)\d+(\)\s+ORDER BY\s+bi_comparison_rank ASC,\s+bi_comparison ASC\s+LIMIT\s+)\d+\s*$/
        const limit = getBIComparisonGroupLimit(worksheet.config)
        return probeClause.test(response.hogql)
            ? response.hogql.replace(probeClause, (_match, prefix, suffix) => `${prefix}${limit}${suffix}${limit * 2}`)
            : null
    }
    return `SELECT * FROM (${response.hogql}) LIMIT ${worksheet.config.limit}`
}
