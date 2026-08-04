import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { BIConfig, BIField, buildBIQuery, isBIFieldCompatible } from './biEditorTypes'

const eventField: BIField = {
    id: 'warehouse:events:event',
    name: 'event',
    expression: 'event',
    type: 'string',
    source: { table: 'events' },
}

const revenueField: BIField = {
    id: 'warehouse:events:properties.revenue',
    name: 'revenue',
    expression: 'properties.revenue',
    type: 'float',
    source: { table: 'events' },
}

describe('BI editor query generation', () => {
    it('builds a visualization node with dimensions, aggregations, and filters', () => {
        const expectedQuery = [
            'SELECT',
            '    event,',
            '    sum(properties.revenue) AS sum_revenue',
            'FROM events',
            'WHERE',
            "    lower(event) LIKE lower('%sign\\'up%')",
            'GROUP BY',
            '    event',
            'LIMIT 1000',
        ].join('\n')
        const config: BIConfig = {
            source: { table: 'events' },
            chartType: ChartDisplayType.ActionsBar,
            rows: [eventField],
            columns: [],
            values: [{ field: revenueField, aggregation: 'sum' }],
            filters: [{ field: eventField, operator: 'contains', value: "sign'up" }],
            limit: 1000,
        }

        expect(buildBIQuery(config)).toEqual({
            query: expectedQuery,
            node: {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: expectedQuery,
                    connectionId: undefined,
                },
                display: ChartDisplayType.ActionsBar,
            },
        })
    })

    it('uses a row count when no value field has been added', () => {
        const result = buildBIQuery({
            source: { table: 'events' },
            chartType: ChartDisplayType.Auto,
            rows: [eventField],
            columns: [],
            values: [],
            filters: [],
            limit: 100,
        })

        expect(result?.query).toContain('count(*) AS count')
    })

    test.each([
        ['the selected table', { ...eventField, expression: 'properties.browser' }, true],
        ['a different table', { ...eventField, source: { table: 'persons' } }, false],
        [
            'the same table on another connection',
            { ...eventField, source: { table: 'events', connectionId: '1' } },
            false,
        ],
    ])('accepts fields from %s according to the active source', (_name, field, expected) => {
        expect(isBIFieldCompatible({ table: 'events' }, field)).toBe(expected)
    })
})
