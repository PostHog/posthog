import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, DashboardTemplateStoredTile, DashboardTemplateType } from '~/types'

import { applyMetricTemplateVariant, applyTemplate } from './newDashboardLogic'

describe('template function in newDashboardLogic', () => {
    it('ignores unused variables', () => {
        expect(
            applyTemplate(
                { a: 'hello', b: 'hi' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            event: '$pageview',
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                null
            )
        ).toEqual({ a: 'hello', b: 'hi' })
    })
    it('uses identified variables', () => {
        expect(
            applyTemplate(
                { a: '{VARIABLE_1}', b: 'hi' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            event: '$pageview',
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                null
            )
        ).toEqual({
            a: {
                event: '$pageview',
            },
            b: 'hi',
        })
    })

    it('replaces variables in query based tiles', () => {
        expect(
            applyTemplate(
                { a: '{VARIABLE_1}' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            id: '$pageview',
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                NodeKind.TrendsQuery
            )
        ).toEqual({
            a: {
                event: '$pageview',
                kind: 'EventsNode',
                math: 'total',
            },
        })
    })

    it("removes the math property from query based tiles that don't support it", () => {
        expect(
            applyTemplate(
                { a: '{VARIABLE_1}' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            id: '$pageview',
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                NodeKind.LifecycleQuery
            )
        ).toEqual({
            a: {
                event: '$pageview',
                kind: 'EventsNode',
            },
        })
    })

    it('removes the math property from retention insight tiles', () => {
        expect(
            applyTemplate(
                { a: '{VARIABLE_1}' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            id: '$pageview',
                            math: 'dau' as any,
                            type: 'events' as any,
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                NodeKind.RetentionQuery
            )
        ).toEqual({
            a: {
                id: '$pageview',
                type: 'events',
            },
        })
    })

    it.each([
        ['Website Metrics', 'Website Unique Users (Total)'],
        ['Landing Pages Report', 'Unique Users on Landing Page(s)'],
    ])('changes only the %s Metric card for the test variant', (templateName, targetTileName) => {
        const tiles = [
            {
                type: 'INSIGHT',
                name: targetTileName,
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        trendsFilter: { display: ChartDisplayType.BoldNumber },
                    },
                },
            },
            {
                type: 'INSIGHT',
                name: 'Another total',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        trendsFilter: { display: ChartDisplayType.BoldNumber },
                    },
                },
            },
        ] as DashboardTemplateStoredTile[]
        const template = { template_name: templateName, scope: 'global' } as DashboardTemplateType

        expect(applyMetricTemplateVariant(tiles, template, true)).toEqual([
            {
                ...tiles[0],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        trendsFilter: { display: ChartDisplayType.Metric },
                    },
                },
            },
            tiles[1],
        ])
        expect(tiles).toEqual([
            {
                type: 'INSIGHT',
                name: targetTileName,
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        trendsFilter: { display: ChartDisplayType.BoldNumber },
                    },
                },
            },
            tiles[1],
        ])
    })

    it.each([
        { scope: 'global', isTestVariant: false },
        { scope: 'team', isTestVariant: true },
    ] as const)('keeps the template unchanged outside the test', ({ scope, isTestVariant }) => {
        const tiles = [
            {
                type: 'INSIGHT',
                name: 'Website Unique Users (Total)',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        trendsFilter: { display: ChartDisplayType.BoldNumber },
                    },
                },
            },
        ] as DashboardTemplateStoredTile[]
        const template = { template_name: 'Website Metrics', scope } as DashboardTemplateType

        expect(applyMetricTemplateVariant(tiles, template, isTestVariant)).toBe(tiles)
    })
})
