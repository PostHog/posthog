import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, DashboardTile, FunnelVizType, InsightShortId, QueryBasedInsightModel } from '~/types'

import {
    BreakdownColorConfig,
    MULTI_BREAKDOWN_SEPARATOR,
    applyAutoBreakdownColors,
    buildSharedBreakdownValueLookup,
    computeTileFallbackTokens,
    extractBreakdownValues,
    extractBreakdownValuesByTile,
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

        it('handles funnel insights with trends visualization, without a baseline row', () => {
            const tiles = [
                createTestTile({
                    result: [{ breakdown_value: ['Chrome'] }, { breakdown_value: ['Firefox'] }],
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.FunnelsQuery,
                            funnelsFilter: {
                                funnelVizType: FunnelVizType.Trends,
                            },
                        },
                    } as InsightVizNode<InsightQueryNode>,
                }),
            ]

            expect(extractBreakdownValues(tiles, null)).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event' },
                { breakdownValue: 'Firefox', breakdownType: 'event' },
            ])
        })

        it('handles retention insights with a breakdown', () => {
            const retentionTile = (result: any[]): DashboardTile<QueryBasedInsightModel> =>
                createTestTile({
                    result,
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.RetentionQuery,
                            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                        },
                    } as InsightVizNode<InsightQueryNode>,
                })

            const tiles = [
                retentionTile([
                    { breakdown_value: 'Chrome' },
                    { breakdown_value: 'Chrome' },
                    { breakdown_value: '$$_posthog_breakdown_other_$$' },
                    { breakdown_value: null },
                ]),
                retentionTile([{ breakdown_value: 'Firefox' }]),
            ]

            expect(extractBreakdownValues(tiles, null)).toEqual([
                { breakdownValue: '$$_posthog_breakdown_other_$$', breakdownType: 'event' },
                { breakdownValue: 'Chrome', breakdownType: 'event' },
                { breakdownValue: 'Firefox', breakdownType: 'event' },
            ])
        })

        it.each([
            [
                'paths insight',
                createTestTile({
                    result: [{ breakdown_value: 'Chrome' }],
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: { kind: NodeKind.PathsQuery },
                    } as InsightVizNode<InsightQueryNode>,
                }),
            ],
            [
                'time-to-convert funnel',
                createTestTile({
                    result: [{ breakdown_value: 'Chrome' }],
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.FunnelsQuery,
                            funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert },
                        },
                    } as InsightVizNode<InsightQueryNode>,
                }),
            ],
            [
                'retention insight without a breakdown filter',
                createTestTile({
                    result: [{ breakdown_value: 'Chrome' }],
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: { kind: NodeKind.RetentionQuery },
                    } as InsightVizNode<InsightQueryNode>,
                }),
            ],
        ])('ignores %s', (_name, tile) => {
            expect(extractBreakdownValues([tile], null)).toEqual([])
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

    describe('extractBreakdownValuesByTile', () => {
        it('keeps values grouped by tile and deduplicates within a tile', () => {
            const tiles = [
                trendsTile([
                    { action: { order: 0 }, breakdown_value: ['Chrome'] },
                    // second series over the same breakdown repeats the value within the tile
                    { action: { order: 1 }, breakdown_value: ['Chrome'] },
                    { action: { order: 0 }, breakdown_value: ['Firefox'] },
                ]),
                trendsTile([{ action: { order: 0 }, breakdown_value: 'Chrome' }]),
                trendsTile([]),
            ]

            expect(extractBreakdownValuesByTile(tiles)).toEqual([
                [
                    { breakdownValue: 'Chrome', breakdownType: 'event', magnitude: 0 },
                    { breakdownValue: 'Firefox', breakdownType: 'event', magnitude: 0 },
                ],
                [{ breakdownValue: 'Chrome', breakdownType: 'event', magnitude: 0 }],
            ])
        })

        it('sizes values from their rows, preferring aggregated_value and keeping the largest across duplicates', () => {
            const tiles = [
                trendsTile([
                    { action: { order: 0 }, breakdown_value: ['Chrome'], count: 120 },
                    { action: { order: 1 }, breakdown_value: ['Chrome'], count: 80 },
                    { action: { order: 0 }, breakdown_value: ['Firefox'], aggregated_value: 5, count: 999 },
                ]),
                // retention rows carry the cohort size as the first interval's count
                createTestTile({
                    result: [{ breakdown_value: 'Chrome', values: [{ count: 40 }, { count: 10 }] }],
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.RetentionQuery,
                            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                        },
                    } as InsightVizNode<InsightQueryNode>,
                }),
            ]

            expect(extractBreakdownValuesByTile(tiles)).toEqual([
                [
                    { breakdownValue: 'Chrome', breakdownType: 'event', magnitude: 120 },
                    { breakdownValue: 'Firefox', breakdownType: 'event', magnitude: 5 },
                ],
                [{ breakdownValue: 'Chrome', breakdownType: 'event', magnitude: 40 }],
            ])
        })
    })

    describe('applyAutoBreakdownColors', () => {
        const value = (breakdownValue: string): { breakdownValue: string; breakdownType: 'event' } => ({
            breakdownValue,
            breakdownType: 'event',
        })
        // most cases want values shared by two tiles, since single-tile values are not assigned
        const sharedTiles = (...breakdownValues: string[]): { breakdownValue: string; breakdownType: 'event' }[][] => [
            breakdownValues.map(value),
            breakdownValues.map(value),
        ]
        const autoConfig = (
            breakdownValue: string,
            colorToken: BreakdownColorConfig['colorToken']
        ): BreakdownColorConfig => ({ breakdownValue, breakdownType: 'event', colorToken, source: 'auto' })
        const sized = (
            breakdownValue: string,
            magnitude: number
        ): { breakdownValue: string; breakdownType: 'event'; magnitude: number } => ({
            breakdownValue,
            breakdownType: 'event',
            magnitude,
        })

        it('assigns only values that appear on two or more tiles', () => {
            const result = applyAutoBreakdownColors([[value('Chrome'), value('Firefox')], [value('Chrome')]], [])

            // Firefox is unique to one tile, so it keeps position-based colors instead
            expect(result).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1', source: 'auto' },
            ])
        })

        it('fills free slots in value order when sizes tie, appending after existing configs', () => {
            const existing: BreakdownColorConfig[] = [
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-3', source: 'manual' },
            ]

            const result = applyAutoBreakdownColors(sharedTiles('Google', 'Alibaba', 'Chrome'), existing)

            expect(result).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-3', source: 'manual' },
                { breakdownValue: 'Alibaba', breakdownType: 'event', colorToken: 'preset-1', source: 'auto' },
                { breakdownValue: 'Google', breakdownType: 'event', colorToken: 'preset-2', source: 'auto' },
            ])
        })

        it('ranks shared values by series size, largest first, like one merged insight', () => {
            const result = applyAutoBreakdownColors(
                [
                    [sized('Zebra', 100), sized('Apple', 5)],
                    [sized('Zebra', 100), sized('Apple', 5)],
                ],
                []
            )

            // value order would put Apple first; size order matches the insights' own coloring
            expect(result).toEqual([autoConfig('Zebra', 'preset-1'), autoConfig('Apple', 'preset-2')])
        })

        it('ranks by the highest size across tiles, not the first seen', () => {
            const result = applyAutoBreakdownColors(
                [
                    [sized('Zeta', 10), sized('Alpha', 50)],
                    [sized('Zeta', 200), sized('Alpha', 50)],
                ],
                []
            )

            expect(result).toEqual([autoConfig('Zeta', 'preset-1'), autoConfig('Alpha', 'preset-2')])
        })

        it('moves the smaller series when two persisted auto entries collide', () => {
            const existing: BreakdownColorConfig[] = [autoConfig('Zeta', 'preset-1'), autoConfig('Alpha', 'preset-1')]

            const result = applyAutoBreakdownColors(
                [
                    [sized('Zeta', 100), sized('Alpha', 5)],
                    [sized('Zeta', 100), sized('Alpha', 5)],
                ],
                existing
            )

            // the larger series is the more recognizable one, so it keeps its color
            expect(result).toEqual([autoConfig('Zeta', 'preset-1'), autoConfig('Alpha', 'preset-2')])
        })

        it('returns non-colliding configs unchanged, by reference, in their original order', () => {
            const existing: BreakdownColorConfig[] = [
                autoConfig('Google', 'preset-2'),
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-3', source: 'manual' },
                autoConfig('Alibaba', 'preset-1'),
            ]

            const result = applyAutoBreakdownColors(sharedTiles('Google', 'Alibaba', 'Chrome'), existing)

            // an unchanged dashboard must round-trip deep-equal, or every load looks like an edit to save
            expect(result).toHaveLength(3)
            result.forEach((config, index) => expect(config).toBe(existing[index]))
        })

        it('keeps covered values stable when a lexically-middle value appears', () => {
            const persistedAuto: BreakdownColorConfig[] = [
                autoConfig('Alibaba', 'preset-1'),
                autoConfig('Google', 'preset-2'),
            ]

            const result = applyAutoBreakdownColors(sharedTiles('Alibaba', 'Bing', 'Google'), persistedAuto)

            // Bing sorts between the two covered values but only takes a free slot
            expect(result).toEqual([...persistedAuto, autoConfig('Bing', 'preset-3')])
        })

        it('skips sentinel values', () => {
            const result = applyAutoBreakdownColors(
                sharedTiles('Baseline', '$$_posthog_breakdown_other_$$', '$$_posthog_breakdown_null_$$', 'Chrome'),
                []
            )

            expect(result).toEqual([autoConfig('Chrome', 'preset-1')])
        })

        it('assigns a value again when its pin was cleared with a null token', () => {
            const result = applyAutoBreakdownColors(sharedTiles('Chrome'), [
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: null, source: 'manual' },
            ])

            expect(result).toEqual([autoConfig('Chrome', 'preset-1')])
        })

        it('sizes slots to the given palette instead of the default 15 colors', () => {
            const existing: BreakdownColorConfig[] = [
                { breakdownValue: 'Pinned', breakdownType: 'event', colorToken: 'preset-7', source: 'manual' },
            ]

            const result = applyAutoBreakdownColors(sharedTiles('A', 'B', 'C', 'D', 'E'), existing, 5)

            // preset-7 renders as the second color of a five-color theme, so that slot is taken.
            // E exhausts the palette, and since the pinned value is not on E's tiles, reusing the
            // pin's slot is a cross-tile duplicate instead of a within-tile one.
            expect(result.slice(1).map((c) => c.colorToken)).toEqual([
                'preset-1',
                'preset-3',
                'preset-4',
                'preset-5',
                'preset-2',
            ])
        })

        it('spreads within-tile duplicates evenly once every slot is on the tile', () => {
            const breakdownValues = Array.from({ length: 17 }, (_, i) => `value-${String(i + 1).padStart(2, '0')}`)

            const result = applyAutoBreakdownColors(sharedTiles(...breakdownValues), [])

            expect(result).toHaveLength(17)
            expect(result[14].colorToken).toBe('preset-15')
            // values 16 and 17 must collide within the tile, but on the least-used slots
            expect(result[15].colorToken).toBe('preset-1')
            expect(result[16].colorToken).toBe('preset-2')
        })

        it('prefers a globally-used slot its own tiles do not show over a within-tile duplicate', () => {
            const tiles = [...sharedTiles('A', 'B'), ...sharedTiles('Z')]

            const result = applyAutoBreakdownColors(tiles, [], 2)

            // the palette is exhausted by A and B, but Z's tiles show neither slot,
            // so Z reuses a color rather than duplicating one on its own charts
            expect(result).toEqual([
                autoConfig('A', 'preset-1'),
                autoConfig('B', 'preset-2'),
                autoConfig('Z', 'preset-1'),
            ])
        })

        it('re-slots the later-sorted persisted auto entry of a within-tile collision, in place', () => {
            const existing: BreakdownColorConfig[] = [autoConfig('Bravo', 'preset-1'), autoConfig('Alpha', 'preset-1')]

            const result = applyAutoBreakdownColors(sharedTiles('Alpha', 'Bravo'), existing)

            // both entries came out of the pre-collision-aware wrap; Alpha sorts first and keeps the slot
            expect(result).toEqual([autoConfig('Bravo', 'preset-2'), autoConfig('Alpha', 'preset-1')])
        })

        it('re-slots a persisted auto entry that collides with a manual pin', () => {
            const existing: BreakdownColorConfig[] = [
                autoConfig('Alpha', 'preset-3'),
                { breakdownValue: 'Pinned', breakdownType: 'event', colorToken: 'preset-3', source: 'manual' },
            ]

            const result = applyAutoBreakdownColors(sharedTiles('Alpha', 'Pinned'), existing)

            expect(result).toEqual([autoConfig('Alpha', 'preset-1'), existing[1]])
        })

        it('never moves manual pins, even when two of them collide on one tile', () => {
            const pins: BreakdownColorConfig[] = [
                { breakdownValue: 'One', breakdownType: 'event', colorToken: 'preset-5', source: 'manual' },
                { breakdownValue: 'Two', breakdownType: 'event', colorToken: 'preset-5', source: 'manual' },
            ]

            const result = applyAutoBreakdownColors(sharedTiles('One', 'Two', 'Three'), pins)

            expect(result).toEqual([...pins, autoConfig('Three', 'preset-1')])
        })
    })

    describe('buildSharedBreakdownValueLookup', () => {
        it('is true only for values appearing on two or more tiles', () => {
            const isShared = buildSharedBreakdownValueLookup([
                [
                    { breakdownValue: 'Chrome', breakdownType: 'event' },
                    { breakdownValue: 'Firefox', breakdownType: 'event' },
                ],
                [{ breakdownValue: 'Chrome', breakdownType: 'event' }],
            ])

            expect(isShared({ breakdownValue: 'Chrome', breakdownType: 'event' })).toBe(true)
            expect(isShared({ breakdownValue: 'Firefox', breakdownType: 'event' })).toBe(false)
            expect(isShared({ breakdownValue: 'Chrome', breakdownType: 'person' })).toBe(false)
        })
    })

    describe('computeTileFallbackTokens', () => {
        it('returns an empty map for a tile without overrides, keeping plain position colors', () => {
            const tokens = computeTileFallbackTokens(
                [
                    { position: 0, overrideToken: null },
                    { position: 1, overrideToken: null },
                ],
                15
            )

            expect(tokens.size).toBe(0)
        })

        it('keeps non-colliding series on their position colors and moves only the displaced one', () => {
            const tokens = computeTileFallbackTokens(
                [
                    { position: 0, overrideToken: 'preset-4' },
                    { position: 1, overrideToken: null },
                    { position: 2, overrideToken: null },
                    { position: 3, overrideToken: null },
                    { position: 4, overrideToken: null },
                ],
                15
            )

            // the override occupies slot 3, so only the position-3 series moves, to the lowest
            // slot the tile leaves unused; everyone else keeps their standalone insight color
            expect(tokens).toEqual(
                new Map([
                    [1, 'preset-2'],
                    [2, 'preset-3'],
                    [3, 'preset-1'],
                    [4, 'preset-5'],
                ])
            )
        })

        it('assigns one slot per position when compare pairs repeat a position', () => {
            const tokens = computeTileFallbackTokens(
                [
                    { position: 0, overrideToken: null },
                    { position: 0, overrideToken: null },
                    { position: 1, overrideToken: 'preset-1' },
                ],
                15
            )

            expect(tokens).toEqual(new Map([[0, 'preset-2']]))
        })

        it('cycles the free slots once exhausted instead of reusing an override slot', () => {
            const tokens = computeTileFallbackTokens(
                [
                    { position: 0, overrideToken: 'preset-1' },
                    { position: 1, overrideToken: null },
                    { position: 2, overrideToken: null },
                    { position: 3, overrideToken: null },
                    { position: 4, overrideToken: null },
                ],
                3
            )

            expect(tokens).toEqual(
                new Map([
                    [1, 'preset-2'],
                    [2, 'preset-3'],
                    [3, 'preset-2'],
                    [4, 'preset-3'],
                ])
            )
        })

        it('returns an empty map when overrides cover the whole palette', () => {
            const tokens = computeTileFallbackTokens(
                [
                    { position: 0, overrideToken: 'preset-1' },
                    { position: 1, overrideToken: 'preset-2' },
                    { position: 2, overrideToken: null },
                ],
                2
            )

            expect(tokens.size).toBe(0)
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
