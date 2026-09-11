import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, DashboardTemplateStoredTile, DashboardTemplateType } from '~/types'

import { applyMetricTemplateVariant, applyTemplate } from './newDashboardLogic'
import { WEBSITE_METRICS_METRIC_CARD_TILES } from './websiteMetricsMetricCardTemplate'

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

    const boldNumberTile = (name: string, extra: Record<string, unknown> = {}): DashboardTemplateStoredTile =>
        ({
            type: 'INSIGHT',
            name,
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.BoldNumber },
                },
            },
            ...extra,
        }) as DashboardTemplateStoredTile
    it('swaps in the Metric card tiles for the Website Metrics test variant', () => {
        const tiles = [boldNumberTile('Website Unique Users (Total)')]
        const template = { template_name: 'Website Metrics', scope: 'global' } as DashboardTemplateType

        expect(applyMetricTemplateVariant(tiles, template, true)).toBe(WEBSITE_METRICS_METRIC_CARD_TILES)
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
