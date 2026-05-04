import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'

import { applyExecuteSqlToolOutput, getExecuteSqlToolContext } from './maxSqlTool'

describe('maxSqlTool', () => {
    const sourceQuery: DataVisualizationNode = {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: 'SELECT count() FROM events WHERE {filters}',
            filters: { dateRange: { date_from: '-30d' } },
            response: { results: [] },
        },
        response: undefined,
    }

    it('passes a query node without response payloads as context', () => {
        const context = getExecuteSqlToolContext('SELECT 1', sourceQuery)

        expect(context.current_query).toEqual('SELECT 1')
        expect(context.current_query_node).toEqual({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT count() FROM events WHERE {filters}',
                filters: { dateRange: { date_from: '-30d' } },
            },
        })
    })

    it('handles legacy string tool output', () => {
        const setSourceQuery = jest.fn()
        const setSuggestedQueryInput = jest.fn()

        applyExecuteSqlToolOutput({
            toolOutput: 'SELECT event FROM events',
            queryInput: 'SELECT count() FROM events',
            sourceQuery,
            setSourceQuery,
            setSuggestedQueryInput,
        })

        expect(setSourceQuery).not.toHaveBeenCalled()
        expect(setSuggestedQueryInput).toHaveBeenCalledWith('SELECT event FROM events', 'max_ai')
    })

    it('applies filters from HogQL query tool output', () => {
        const setSourceQuery = jest.fn()
        const setSuggestedQueryInput = jest.fn()

        applyExecuteSqlToolOutput({
            toolOutput: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT event FROM events WHERE {filters}',
                filters: { dateRange: { date_from: '-90d' } },
            },
            queryInput: 'SELECT count() FROM events WHERE {filters}',
            sourceQuery,
            setSourceQuery,
            setSuggestedQueryInput,
        })

        expect(setSourceQuery).toHaveBeenCalledWith({
            ...sourceQuery,
            source: {
                ...sourceQuery.source,
                filters: { dateRange: { date_from: '-90d' } },
            },
        })
        expect(setSuggestedQueryInput).toHaveBeenCalledWith('SELECT event FROM events WHERE {filters}', 'max_ai')
    })

    it('clears filters from explicit null tool output', () => {
        const setSourceQuery = jest.fn()
        const setSuggestedQueryInput = jest.fn()

        applyExecuteSqlToolOutput({
            toolOutput: {
                source: {
                    query: 'SELECT count() FROM events WHERE {filters}',
                    filters: null,
                },
            },
            queryInput: 'SELECT count() FROM events WHERE {filters}',
            sourceQuery,
            setSourceQuery,
            setSuggestedQueryInput,
        })

        expect(setSourceQuery).toHaveBeenCalledWith({
            ...sourceQuery,
            source: {
                ...sourceQuery.source,
                filters: undefined,
            },
        })
        expect(setSuggestedQueryInput).not.toHaveBeenCalled()
    })
})
