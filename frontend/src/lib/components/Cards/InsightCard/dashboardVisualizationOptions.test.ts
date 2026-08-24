import { DataVisualizationNode, FunnelsQuery, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'

import { resolveVisualizationPicker } from './dashboardVisualizationOptions'

describe('resolveVisualizationPicker', () => {
    const persist = (): void => {}

    const sqlQuery = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    } as DataVisualizationNode

    const trendsQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.TrendsQuery, series: [] },
    } as unknown as InsightVizNode

    const funnelQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.FunnelsQuery, series: [] } as unknown as FunnelsQuery,
    } as unknown as InsightVizNode

    it.each([
        {
            label: 'SQL insight gets the SQL picker',
            query: sqlQuery as Node,
            supportsDisplay: false,
            canPersist: true,
            expected: 'sql',
        },
        {
            label: 'trends-family insight gets the trends picker',
            query: trendsQuery as Node,
            supportsDisplay: true,
            canPersist: true,
            expected: 'trends',
        },
        {
            label: 'funnel gets nothing, since its chart type is not a single dropdown',
            query: funnelQuery as Node,
            supportsDisplay: false,
            canPersist: true,
            expected: undefined,
        },
        {
            label: 'no picker when the change cannot be saved, so a viewer never gets a control that no-ops',
            query: sqlQuery as Node,
            supportsDisplay: false,
            canPersist: false,
            expected: undefined,
        },
        {
            label: 'no picker without a query',
            query: null,
            supportsDisplay: true,
            canPersist: true,
            expected: undefined,
        },
    ])('$label', ({ query, supportsDisplay, canPersist, expected }) => {
        const picker = resolveVisualizationPicker(query, supportsDisplay, canPersist ? persist : undefined)
        expect(picker?.kind).toBe(expected)
    })

    it('hands the SQL picker the narrowed query, so the caller does not re-derive it', () => {
        const picker = resolveVisualizationPicker(sqlQuery as Node, false, persist)

        expect(picker).toMatchObject({ kind: 'sql', query: sqlQuery })
    })
})
