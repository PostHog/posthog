import { AnyResponseType, NodeKind, VisualizationNode } from '~/queries/schema/schema-general'

import { buildBIQuery } from './biEditorTypes'

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
    return {
        ...response,
        results: response.results.slice(0, query.config.limit),
        hasMore: response.results.length > query.config.limit || ('hasMore' in response && response.hasMore === true),
    }
}
