import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, DashboardTile, FunnelVizType, InsightShortId, QueryBasedInsightModel } from '~/types'

import {
    BreakdownColorConfig,
    MULTI_BREAKDOWN_SEPARATOR,
    computeAutoBreakdownColors,
    extractBreakdownValues,
    findBreakdownColorConfig,
    mergeBreakdownColorConfigs,
} from './dashboardBreakdownColors'

describe('dashboardBreakdownColors', () => {
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

    const trendsTile = (result: any[]): DashboardTile<QueryBasedInsightModel> =>
        createTestTile({
            result,
            query: {
                kind: NodeKind.InsightVizNode,
                source: { kind: NodeKind.TrendsQuery },
            } as InsightVizNode<InsightQueryNode>,
        })

    describe('extractBreakdownValues', () => {
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

            expect(extractBreakdownValues(tiles, null)).toEqual([
                { breakdownValue: 'Baseline', breakdownType: 'event' },
                { breakdownValue: 'Chrome', breakdownType: 'event' },
                { breakdownValue: 'Firefox', breakdownType: 'event' },
                { breakdownValue: 'Safari', breakdownType: 'event' },
            ])
        })

        it('handles trends insights', () => {
            const tiles = [
                trendsTile([
                    { action: { order: 0 }, breakdown_value: ['Chrome'], compare_label: 'previous' },
                    { action: { order: 0 }, breakdown_value: ['Firefox'], compare_label: 'previous' },
                ]),
                trendsTile([{ action: { order: 0 }, breakdown_value: 'Safari' }]),
            ]

            expect(extractBreakdownValues(tiles, null)).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event' },
                { breakdownValue: 'Firefox', breakdownType: 'event' },
                { breakdownValue: 'Safari', breakdownType: 'event' },
            ])
        })

        it('deduplicates repeated breakdown values across tiles', () => {
            const tiles = [
                trendsTile([
                    { action: { order: 0 }, breakdown_value: ['Chrome'] },
                    { action: { order: 1 }, breakdown_value: ['Firefox'] },
                ]),
                trendsTile([
                    { action: { order: 0 }, breakdown_value: ['Chrome'] },
                    { action: { order: 1 }, breakdown_value: ['Safari'] },
                ]),
            ]

            expect(extractBreakdownValues(tiles, null)).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event' },
                { breakdownValue: 'Firefox', breakdownType: 'event' },
                { breakdownValue: 'Safari', breakdownType: 'event' },
            ])
        })

        it('stringifies numeric values so trends and funnels tiles share one entry', () => {
            const tiles = [
                // trends keys wrap scalars in an array; funnels keep them bare
                trendsTile([{ action: { order: 0 }, breakdown_value: [123] }]),
                createTestTile({
                    result: [{ breakdown_value: 123 }],
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: { kind: NodeKind.FunnelsQuery },
                    } as InsightVizNode<InsightQueryNode>,
                }),
            ]

            expect(extractBreakdownValues(tiles, null)).toEqual([
                { breakdownValue: '123', breakdownType: 'event' },
                { breakdownValue: 'Baseline', breakdownType: 'event' },
            ])
        })

        it('ignores non-matching insight types', () => {
            const tiles = [
                createTestTile({
                    result: [],
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: { kind: NodeKind.RetentionQuery },
                    } as InsightVizNode<InsightQueryNode>,
                }),
            ]
            expect(extractBreakdownValues(tiles, null)).toEqual([])
        })

        it('handles cohort breakdowns', () => {
            const cohortTile = (values: number[][]): DashboardTile<QueryBasedInsightModel> =>
                createTestTile({
                    result: values.map((breakdown_value) => ({ action: { order: 0 }, breakdown_value })),
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            breakdownFilter: { breakdown_type: 'cohort' },
                        },
                    } as InsightVizNode<InsightQueryNode>,
                })

            expect(extractBreakdownValues([cohortTile([[1], [2]]), cohortTile([[3]])], null)).toEqual([
                { breakdownValue: '1', breakdownType: 'cohort' },
                { breakdownValue: '2', breakdownType: 'cohort' },
                { breakdownValue: '3', breakdownType: 'cohort' },
            ])
        })
    })

    describe('computeAutoBreakdownColors', () => {
        const value = (breakdownValue: string): { breakdownValue: string; breakdownType: 'event' } => ({
            breakdownValue,
            breakdownType: 'event',
        })

        it('fills free slots in sorted order without touching existing configs', () => {
            const existing: BreakdownColorConfig[] = [
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-3', source: 'manual' },
            ]

            const assigned = computeAutoBreakdownColors([value('Google'), value('Alibaba'), value('Chrome')], existing)

            expect(assigned).toEqual([
                { breakdownValue: 'Alibaba', breakdownType: 'event', colorToken: 'preset-1', source: 'auto' },
                { breakdownValue: 'Google', breakdownType: 'event', colorToken: 'preset-2', source: 'auto' },
            ])
            expect(existing[0].colorToken).toBe('preset-3')
        })

        it('keeps covered values stable when a lexically-middle value appears', () => {
            const persistedAuto: BreakdownColorConfig[] = [
                { breakdownValue: 'Alibaba', breakdownType: 'event', colorToken: 'preset-1', source: 'auto' },
                { breakdownValue: 'Google', breakdownType: 'event', colorToken: 'preset-2', source: 'auto' },
            ]

            const assigned = computeAutoBreakdownColors(
                [value('Alibaba'), value('Bing'), value('Google')],
                persistedAuto
            )

            // Bing sorts between the two covered values but only takes a free slot
            expect(assigned).toEqual([
                { breakdownValue: 'Bing', breakdownType: 'event', colorToken: 'preset-3', source: 'auto' },
            ])
        })

        it('skips sentinel values', () => {
            const assigned = computeAutoBreakdownColors(
                [
                    value('Baseline'),
                    value('$$_posthog_breakdown_other_$$'),
                    value('$$_posthog_breakdown_null_$$'),
                    value('Chrome'),
                ],
                []
            )

            expect(assigned).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1', source: 'auto' },
            ])
        })

        it('assigns a value again when its pin was cleared with a null token', () => {
            const assigned = computeAutoBreakdownColors(
                [value('Chrome')],
                [{ breakdownValue: 'Chrome', breakdownType: 'event', colorToken: null, source: 'manual' }]
            )

            expect(assigned).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1', source: 'auto' },
            ])
        })

        it('sizes slots to the given palette instead of the default 15 colors', () => {
            const existing: BreakdownColorConfig[] = [
                { breakdownValue: 'Pinned', breakdownType: 'event', colorToken: 'preset-7', source: 'manual' },
            ]

            const assigned = computeAutoBreakdownColors(
                [value('A'), value('B'), value('C'), value('D'), value('E')],
                existing,
                5
            )

            // preset-7 renders as the second color of a five-color theme, so that slot is taken,
            // and the fifth value wraps at the palette size rather than taking preset-6
            expect(assigned.map((c) => c.colorToken)).toEqual([
                'preset-1',
                'preset-3',
                'preset-4',
                'preset-5',
                'preset-1',
            ])
        })

        it('wraps deterministically once the palette is exhausted', () => {
            const values = Array.from({ length: 17 }, (_, i) => value(`value-${String(i + 1).padStart(2, '0')}`))

            const assigned = computeAutoBreakdownColors(values, [])

            expect(assigned).toHaveLength(17)
            expect(assigned[14].colorToken).toBe('preset-15')
            expect(assigned[15].colorToken).toBe('preset-1')
            expect(assigned[16].colorToken).toBe('preset-2')
        })
    })

    describe('mergeBreakdownColorConfigs', () => {
        it('lets earlier lists win and deduplicates by value and type', () => {
            const merged = mergeBreakdownColorConfigs(
                [{ breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-5', source: 'manual' }],
                [
                    { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1' },
                    { breakdownValue: 'Firefox', breakdownType: 'event', colorToken: 'preset-2' },
                ]
            )

            expect(merged).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-5', source: 'manual' },
                { breakdownValue: 'Firefox', breakdownType: 'event', colorToken: 'preset-2' },
            ])
        })

        it('normalizes legacy non-string values', () => {
            const merged = mergeBreakdownColorConfigs([
                { breakdownValue: 123 as any, breakdownType: 'event', colorToken: 'preset-1' },
            ])

            expect(merged).toEqual([{ breakdownValue: '123', breakdownType: 'event', colorToken: 'preset-1' }])
        })
    })

    describe('findBreakdownColorConfig', () => {
        const configs: BreakdownColorConfig[] = [
            { breakdownValue: '123', breakdownType: 'event', colorToken: 'preset-1' },
            { breakdownValue: 'a::b', breakdownType: 'event', colorToken: 'preset-2' },
            { breakdownValue: 'Chrome', breakdownType: 'person', colorToken: 'preset-3' },
            {
                breakdownValue: ['a', 'b'].join(MULTI_BREAKDOWN_SEPARATOR),
                breakdownType: 'event',
                colorToken: 'preset-4',
            },
        ]

        it.each([
            ['numeric dataset value matches a stringified config', 123, 'event', 'preset-1'],
            [
                'multi-breakdown array matches its own entry, not a scalar containing "::"',
                ['a', 'b'],
                'event',
                'preset-4',
            ],
            ['scalar containing "::" matches its own entry, not a multi-breakdown array', 'a::b', 'event', 'preset-2'],
            ['breakdown type must match', 'Chrome', 'event', undefined],
            ['type defaults to event when not provided', '123', undefined, 'preset-1'],
        ] as const)('%s', (_name, breakdownValue, breakdownType, expectedToken) => {
            expect(findBreakdownColorConfig(configs, breakdownValue, breakdownType as any)?.colorToken).toEqual(
                expectedToken
            )
        })

        it('returns undefined for null or undefined dataset values', () => {
            expect(findBreakdownColorConfig(configs, undefined, 'event')).toBeUndefined()
            expect(findBreakdownColorConfig(configs, null, 'event')).toBeUndefined()
        })
    })
})
