import { AnyResponseType, NodeKind, VisualizationNode } from '~/queries/schema/schema-general'

import { getBIComparisonGroupLimit } from './biComparisonLimit'
import { buildBIQuery, getBIResultDimensions } from './biEditorTypes'

export function getBIVisualizationSource(query: VisualizationNode): VisualizationNode['source'] {
    if (query.kind !== NodeKind.BIVisualizationNode) {
        return query.source
    }
    const probe = buildBIQuery(query.config, true)
    return probe ? { ...query.source, query: probe.query } : query.source
}

export function getBIVisualizationResponse(
    query: VisualizationNode,
    response: AnyResponseType | null
): AnyResponseType | null {
    if (
        query.kind !== NodeKind.BIVisualizationNode ||
        !response ||
        !('results' in response) ||
        !Array.isArray(response.results)
    ) {
        return response
    }
    if (query.config.compareFilter?.compare) {
        const columns = 'columns' in response && Array.isArray(response.columns) ? response.columns : []
        const dimensions = getBIResultDimensions(query.config).map(({ column }) => columns.indexOf(column))
        const key = (row: unknown[]): string => JSON.stringify(dimensions.map((index) => row[index]))
        const groups = new Set(response.results.map(key))
        const selected = new Set([...groups].slice(0, getBIComparisonGroupLimit(query.config)))
        return {
            ...response,
            results: response.results.filter((row) => selected.has(key(row))),
            hasMore: groups.size > selected.size || ('hasMore' in response && response.hasMore === true),
        }
    }
    return {
        ...response,
        results: response.results.slice(0, query.config.limit),
        hasMore: response.results.length > query.config.limit || ('hasMore' in response && response.hasMore === true),
    }
}
