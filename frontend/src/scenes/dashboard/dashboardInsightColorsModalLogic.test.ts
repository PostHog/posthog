import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, DashboardTile, FunnelVizType, InsightShortId, QueryBasedInsightModel } from '~/types'

import { extractBreakdownValues } from './dashboardInsightColorsModalLogic'

describe('extractBreakdownValues', () => {
    const createTestTile = (
        overrides: Partial<QueryBasedInsightModel> = {}
    ): DashboardTile<QueryBasedInsightModel> => ({
        id: 1,
        layouts: {},
        color: null,
        insight: {
            short_id: 'abc123' as InsightShortId,
            id: 1,
            name: 'Test Insight',
            order: null,
            result: [],
            deleted: false,
            saved: true,
            created_at: '2023-01-01T00:00:00Z',
            created_by: null,
            is_sample: false,
            dashboards: null,
            dashboard_tiles: null,
            updated_at: '2023-01-01T00:00:00Z',
            last_modified_at: '2023-01-01T00:00:00Z',
            last_modified_by: null,
            query: null,
            last_refresh: null,
            user_access_level: AccessControlLevel.None,
            ...overrides,
        },
    })

    it('returns empty array for null input', () => {
        expect(extractBreakdownValues(null, null)).toEqual([])
    })

    it('handles funnel insights with steps visualization', () => {
        const tiles = [
            createTestTile({
                result: [{ breakdown_value: ['Chrome'] }, { breakdown_value: ['Firefox'] }],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: {
                            funnelVizType: FunnelVizType.Steps,
                        },
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
            createTestTile({
                result: [{ breakdown_value: 'Safari' }],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: {
                            funnelVizType: FunnelVizType.Steps,
                        },
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
        ]

        const result = extractBreakdownValues(tiles, null)

        expect(result).toEqual([
            { breakdownValue: 'Baseline', breakdownType: 'event' },
            { breakdownValue: 'Chrome', breakdownType: 'event' },
            { breakdownValue: 'Firefox', breakdownType: 'event' },
            { breakdownValue: 'Safari', breakdownType: 'event' },
        ])
    })

    it('handles trends insights', () => {
        const tiles = [
            createTestTile({
                result: [
                    { action: { order: 0 }, breakdown_value: ['Chrome'], compare_label: 'previous' },
                    { action: { order: 0 }, breakdown_value: ['Firefox'], compare_label: 'previous' },
                ],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
            createTestTile({
                result: [{ action: { order: 0 }, breakdown_value: 'Safari' }],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
        ]

        const result = extractBreakdownValues(tiles, null)

        expect(result).toEqual([
            { breakdownValue: 'Chrome', breakdownType: 'event' },
            { breakdownValue: 'Firefox', breakdownType: 'event' },
            { breakdownValue: 'Safari', breakdownType: 'event' },
        ])
    })

    it('deduplicates repeated breakdown values across tiles', () => {
        const tiles = [
            createTestTile({
                result: [
                    { action: { order: 0 }, breakdown_value: ['Chrome'] },
                    { action: { order: 1 }, breakdown_value: ['Firefox'] },
                ],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
            createTestTile({
                result: [
                    { action: { order: 0 }, breakdown_value: ['Chrome'] },
                    { action: { order: 1 }, breakdown_value: ['Safari'] },
                ],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
        ]

        const result = extractBreakdownValues(tiles, null)

        expect(result).toEqual([
            { breakdownValue: 'Chrome', breakdownType: 'event' },
            { breakdownValue: 'Firefox', breakdownType: 'event' },
            { breakdownValue: 'Safari', breakdownType: 'event' },
        ])
    })

    it('ignores non-matching insight types', () => {
        const tiles = [
            createTestTile({
                result: [],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.RetentionQuery,
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
        ]
        expect(extractBreakdownValues(tiles, null)).toEqual([])
    })

    it('handles cohort breakdowns', () => {
        const tiles = [
            createTestTile({
                result: [
                    { action: { order: 0 }, breakdown_value: [1] },
                    { action: { order: 0 }, breakdown_value: [2] },
                ],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        breakdownFilter: {
                            breakdown_type: 'cohort',
                        },
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
            createTestTile({
                result: [{ action: { order: 0 }, breakdown_value: [3] }],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        breakdownFilter: {
                            breakdown_type: 'cohort',
                        },
                    },
                } as InsightVizNode<InsightQueryNode>,
            }),
        ]

        const result = extractBreakdownValues(tiles, null)

        expect(result).toEqual([
            { breakdownValue: '1', breakdownType: 'cohort' },
            { breakdownValue: '2', breakdownType: 'cohort' },
            { breakdownValue: '3', breakdownType: 'cohort' },
        ])
    })
})
