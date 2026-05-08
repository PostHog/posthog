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

    it.each([
        {
            name: 'handles legacy string tool output',
            toolOutput: 'SELECT event FROM events',
            queryInput: 'SELECT count() FROM events',
            expectedSourceQuery: null,
            expectedSuggestedQueryInput: ['SELECT event FROM events', 'max_ai'],
        },
        {
            name: 'applies filters from HogQL query tool output',
            toolOutput: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT event FROM events WHERE {filters}',
                filters: { dateRange: { date_from: '-90d' } },
            },
            queryInput: 'SELECT count() FROM events WHERE {filters}',
            expectedSourceQuery: {
                ...sourceQuery,
                source: {
                    ...sourceQuery.source,
                    filters: { dateRange: { date_from: '-90d' } },
                },
            },
            expectedSuggestedQueryInput: ['SELECT event FROM events WHERE {filters}', 'max_ai'],
        },
        {
            name: 'clears filters from empty backend filters payload',
            toolOutput: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT count() FROM events WHERE {filters}',
                filters: {},
            },
            queryInput: 'SELECT count() FROM events WHERE {filters}',
            expectedSourceQuery: {
                ...sourceQuery,
                source: {
                    ...sourceQuery.source,
                    filters: {},
                },
            },
            expectedSuggestedQueryInput: null,
        },
    ])('$name', ({ toolOutput, queryInput, expectedSourceQuery, expectedSuggestedQueryInput }) => {
        const setSourceQuery = jest.fn()
        const setSuggestedQueryInput = jest.fn()

        applyExecuteSqlToolOutput({
            toolOutput,
            queryInput,
            sourceQuery,
            setSourceQuery,
            setSuggestedQueryInput,
        })

        if (expectedSourceQuery) {
            expect(setSourceQuery).toHaveBeenCalledWith(expectedSourceQuery)
        } else {
            expect(setSourceQuery).not.toHaveBeenCalled()
        }

        if (expectedSuggestedQueryInput) {
            expect(setSuggestedQueryInput).toHaveBeenCalledWith(...expectedSuggestedQueryInput)
        } else {
            expect(setSuggestedQueryInput).not.toHaveBeenCalled()
        }
    })
})
