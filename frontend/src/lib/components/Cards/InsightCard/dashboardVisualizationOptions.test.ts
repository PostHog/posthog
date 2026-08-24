import { DataVisualizationNode, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'

import { shouldShowSqlVisualizationPicker } from './dashboardVisualizationOptions'

describe('shouldShowSqlVisualizationPicker', () => {
    const sqlQuery = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    } as DataVisualizationNode

    const trendsQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.TrendsQuery, series: [] },
    } as unknown as InsightVizNode

    it.each([
        { label: 'SQL insight gets the picker', query: sqlQuery as Node, canPersist: true, expected: true },
        {
            label: 'a trends insight gets nothing, since its chart type carries query side effects',
            query: trendsQuery as Node,
            canPersist: true,
            expected: false,
        },
        {
            label: 'no picker when the change cannot be saved, so a viewer never gets a control that no-ops',
            query: sqlQuery as Node,
            canPersist: false,
            expected: false,
        },
        { label: 'no picker without a query', query: null, canPersist: true, expected: false },
    ])('$label', ({ query, canPersist, expected }) => {
        expect(shouldShowSqlVisualizationPicker(query, canPersist)).toBe(expected)
    })
})
