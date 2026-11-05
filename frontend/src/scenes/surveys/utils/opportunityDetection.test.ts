import { FunnelsQuery, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { FunnelVizType, InsightModel } from '~/types'

import { contextItemPath } from 'products/posthog_ai/frontend/utils/contextItemLink'
import { wrapWithPosthogContext } from 'products/posthog_ai/frontend/utils/posthogContextBlock'

import { isSurveyableFunnelInsight, surveyOpportunityContextItems } from './opportunityDetection'

describe('opportunityDetection', () => {
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

    describe('surveyOpportunityContextItems', () => {
        const funnelContext = { insightName: 'Signups', conversionRate: 0.2, steps: [] }

        const shortId = 'abc123' as InsightModel['short_id']

        test.each<[Partial<Pick<InsightModel, 'id' | 'short_id'>>, string | null]>([
            [{ id: 17, short_id: shortId }, '/insights/abc123'],
            [{ id: 17 }, null],
            [{}, null],
        ])('links %o by short ID and keeps the context key', (insight, expected) => {
            const items = surveyOpportunityContextItems(insight, funnelContext)

            expect(contextItemPath(items![0])).toBe(expected)
            expect(items![0].key).toBe(insight.id)
            expect(items![1]).toEqual({
                type: 'survey_opportunity_funnel_context',
                value: JSON.stringify({ conversionRate: 0.2, steps: [] }),
                label: 'Funnel conversion context',
            })
            if (insight.id) {
                expect(wrapWithPosthogContext('Review this funnel', items!)).toContain(`insight ${insight.id}`)
            }
        })

        it('attaches no context without a surveyable funnel', () => {
            expect(surveyOpportunityContextItems({ id: 17, short_id: shortId }, null)).toBeNull()
        })
    })
})
