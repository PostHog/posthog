import { DataVisualizationNode, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'

import { sqlQueryForVisualizationPicker } from './dashboardVisualizationOptions'

describe('sqlQueryForVisualizationPicker', () => {
    const sqlQuery = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    } as DataVisualizationNode

    const trendsQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.TrendsQuery, series: [] },
    } as unknown as InsightVizNode

    it.each([
        { label: 'SQL insight gets the picker', query: sqlQuery as Node, canPersist: true, expected: sqlQuery },
        {
            label: 'a trends insight gets nothing, since its chart type carries query side effects',
            query: trendsQuery as Node,
            canPersist: true,
            expected: null,
        },
        {
            label: 'no picker when the change cannot be saved, so a viewer never gets a control that no-ops',
            query: sqlQuery as Node,
            canPersist: false,
            expected: null,
        },
        { label: 'no picker without a query', query: null, canPersist: true, expected: null },
    ])('$label', ({ query, canPersist, expected }) => {
        expect(sqlQueryForVisualizationPicker(query, canPersist)).toBe(expected)
    })
})
