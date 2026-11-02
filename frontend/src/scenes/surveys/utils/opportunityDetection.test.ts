import { FunnelsQuery, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { FunnelVizType, InsightModel } from '~/types'

import { isSurveyableFunnelInsight } from './opportunityDetection'

describe('isSurveyableFunnelInsight', () => {
    const pageviews = { kind: NodeKind.EventsNode as const, event: '$pageview', name: '$pageview' }
    const signups = { kind: NodeKind.ActionsNode as const, id: 7, name: 'Signed up' }
    const steps = [
        { name: '$pageview', order: 0, count: 100 },
        { name: 'Signed up', order: 1, count: 20 },
    ]

    const funnelInsight = (source: Partial<FunnelsQuery>, result: unknown): Partial<InsightModel> => ({
        query: {
            kind: NodeKind.InsightVizNode,
            source: { kind: NodeKind.FunnelsQuery, series: [pageviews, signups], ...source },
        } as InsightVizNode<FunnelsQuery>,
        result,
    })

    it.each<[string, Partial<InsightModel>, boolean]>([
        ['a steps funnel of events and actions', funnelInsight({}, steps), true],
        [
            'a funnel with a data warehouse step, which a survey cannot target',
            funnelInsight(
                {
                    series: [
                        pageviews,
                        {
                            kind: NodeKind.FunnelsDataWarehouseNode,
                            id: 'invoices',
                            table_name: 'invoices',
                            id_field: 'id',
                            timestamp_field: 'created_at',
                            aggregation_target_field: 'customer_id',
                        },
                    ],
                },
                steps
            ),
            false,
        ],
        ['a breakdown funnel, which returns steps for each breakdown value', funnelInsight({}, [steps, steps]), false],
        [
            'a trends funnel, which returns conversion over time',
            funnelInsight({ funnelsFilter: { funnelVizType: FunnelVizType.Trends } }, [
                { count: 2, data: [10, 20], days: ['2026-10-01', '2026-10-02'], breakdown_value: 'Chrome' },
                { count: 2, data: [15, 25], days: ['2026-10-01', '2026-10-02'], breakdown_value: 'Safari' },
            ]),
            false,
        ],
    ])('checks %s', (_case, insight, expected) => {
        expect(isSurveyableFunnelInsight(insight)).toBe(expected)
    })
})
