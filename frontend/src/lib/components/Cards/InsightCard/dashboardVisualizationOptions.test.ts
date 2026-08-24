import { DataVisualizationNode, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'

import { resolveVisualizationPicker, VisualizationPickerKind } from './dashboardVisualizationOptions'

describe('resolveVisualizationPicker', () => {
    const sqlQuery = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    } as DataVisualizationNode

    const trendsQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.TrendsQuery, series: [] },
    } as unknown as InsightVizNode

    it.each([
        {
            label: 'SQL insight gets the SQL picker',
            query: sqlQuery as Node,
            supportsDisplay: false,
            canPersist: true,
            expected: 'sql' as VisualizationPickerKind,
        },
        {
            label: 'trends-family insight gets the trends picker',
            query: trendsQuery as Node,
            supportsDisplay: true,
            canPersist: true,
            expected: 'trends' as VisualizationPickerKind,
        },
        {
            label: 'insight whose chart type is not a single dropdown (funnel, retention, paths) gets nothing',
            query: trendsQuery as Node,
            supportsDisplay: false,
            canPersist: true,
            expected: null,
        },
        {
            label: 'no picker when the change cannot be saved, so a viewer never gets a control that no-ops',
            query: sqlQuery as Node,
            supportsDisplay: true,
            canPersist: false,
            expected: null,
        },
        {
            label: 'no picker without a query',
            query: null,
            supportsDisplay: true,
            canPersist: true,
            expected: null,
        },
    ])('$label', ({ query, supportsDisplay, canPersist, expected }) => {
        expect(resolveVisualizationPicker(query, supportsDisplay, canPersist)).toBe(expected)
    })
})
