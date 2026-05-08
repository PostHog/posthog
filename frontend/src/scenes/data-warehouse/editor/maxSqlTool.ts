import type { DataVisualizationNode, HogQLFilters } from '~/queries/schema/schema-general'

type SetSourceQuery = (sourceQuery: DataVisualizationNode) => void
type SetSuggestedQueryInput = (suggestedQueryInput: string, source?: 'max_ai') => void

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getCurrentQueryNodeContext(sourceQuery: DataVisualizationNode): DataVisualizationNode {
    const currentQueryNode = { ...sourceQuery, source: { ...sourceQuery.source } }
    delete currentQueryNode.response
    delete currentQueryNode.source.response
    return currentQueryNode
}

export function getExecuteSqlToolContext(
    queryInput: string | null,
    sourceQuery: DataVisualizationNode
): Record<string, unknown> {
    return {
        current_query: queryInput,
        current_query_node: getCurrentQueryNodeContext(sourceQuery),
    }
}

export function applyExecuteSqlToolOutput({
    toolOutput,
    queryInput,
    sourceQuery,
    setSourceQuery,
    setSuggestedQueryInput,
}: {
    toolOutput: unknown
    queryInput: string | null
    sourceQuery: DataVisualizationNode
    setSourceQuery: SetSourceQuery
    setSuggestedQueryInput: SetSuggestedQueryInput
}): void {
    let nextQueryInput: string | null = null
    let nextFilters: HogQLFilters | null | undefined

    if (typeof toolOutput === 'string') {
        nextQueryInput = toolOutput
    } else if (isRecord(toolOutput)) {
        const sourceOutput = isRecord(toolOutput.source) ? toolOutput.source : null

        if (typeof toolOutput.query === 'string') {
            nextQueryInput = toolOutput.query
        } else if (sourceOutput && typeof sourceOutput.query === 'string') {
            nextQueryInput = sourceOutput.query
        }

        if ('filters' in toolOutput) {
            nextFilters = (toolOutput.filters ?? null) as HogQLFilters | null
        } else if (sourceOutput && 'filters' in sourceOutput) {
            nextFilters = (sourceOutput.filters ?? null) as HogQLFilters | null
        }
    }

    if (nextFilters !== undefined) {
        setSourceQuery({
            ...sourceQuery,
            source: {
                ...sourceQuery.source,
                filters: nextFilters ?? undefined,
            },
        })
    }

    if (nextQueryInput !== null && nextQueryInput !== queryInput) {
        setSuggestedQueryInput(nextQueryInput, 'max_ai')
    }
}
