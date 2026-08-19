import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, DashboardTile, FunnelVizType, InsightShortId, QueryBasedInsightModel } from '~/types'

import {
    BreakdownColorConfig,
    BreakdownValueAndType,
    MULTI_BREAKDOWN_SEPARATOR,
    applyAutoBreakdownColors,
    buildSharedBreakdownValueLookup,
    computeTileFallbackTokens,
    extractBreakdownValues,
    extractBreakdownValuesByTile,
    findBreakdownColorConfig,
    getBreakdownPropertyKey,
    groupBreakdownValuesByProperty,
    hasUnresolvedBreakdownTiles,
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

    const trendsTile = (result: any[], breakdownFilter?: Record<string, any>): DashboardTile<QueryBasedInsightModel> =>
        createTestTile({
            result,
            query: {
                kind: NodeKind.InsightVizNode,
                source: { kind: NodeKind.TrendsQuery, ...(breakdownFilter ? { breakdownFilter } : {}) },
            } as InsightVizNode<InsightQueryNode>,
        })

    describe('getBreakdownPropertyKey', () => {
        it.each([
            ['no filter', undefined, null],
            ['a filter without a breakdown', { breakdown_type: 'event' }, null],
            ['a single event breakdown', { breakdown: '$browser', breakdown_type: 'event' }, 'event::$browser'],
            ['a single breakdown with the type defaulted', { breakdown: '$browser' }, 'event::$browser'],
            [
                'a one-entry multi breakdown',
                { breakdowns: [{ property: '$browser', type: 'event' }] },
                'event::$browser',
            ],
            [
                'a one-entry multi breakdown with the type defaulted',
                { breakdowns: [{ property: '$browser' }] },
                'event::$browser',
            ],
            ['a person property', { breakdown: '$browser', breakdown_type: 'person' }, 'person::$browser'],
            [
                'a group property, keyed by its group type index',
                { breakdown: 'industry', breakdown_type: 'group', breakdown_group_type_index: 2 },
                'group:2:industry',
            ],
            [
                'a stale group type index on a non-group breakdown',
                { breakdown: '$browser', breakdown_type: 'event', breakdown_group_type_index: 2 },
                'event::$browser',
            ],
            [
                'a cohort breakdown, regardless of its cohort ids',
                { breakdown: [1, 2], breakdown_type: 'cohort' },
                'cohort',
            ],
            [
                'display options, which stay out of the key',
                {
                    breakdown: '$current_url',
                    breakdown_type: 'event',
                    breakdown_normalize_url: true,
                    breakdown_histogram_bin_count: 10,
                    breakdown_limit: 25,
                },
                'event::$current_url',
            ],
            [
                'a multi breakdown, joining parts in order',
                { breakdowns: [{ property: '$browser' }, { property: '$os', type: 'person' }] },
                `event::$browser${MULTI_BREAKDOWN_SEPARATOR}person::$os`,
            ],
        ] as const)('normalizes %s', (_name, breakdownFilter, expected) => {
            expect(getBreakdownPropertyKey(breakdownFilter as any)).toEqual(expected)
        })
    })

    describe('extractBreakdownValues', () => {
        it('returns empty array for null input', () => {
            expect(extractBreakdownValues(null)).toEqual([])
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

            // Baseline is on both tiles, so it outranks the single-tile values; Chrome and
            // Safari tie on chart position and fall back to value order
            expect(extractBreakdownValues(tiles)).toEqual([
                { breakdownValue: 'Baseline', breakdownType: 'event' },
                { breakdownValue: 'Chrome', breakdownType: 'event' },
                { breakdownValue: 'Safari', breakdownType: 'event' },
                { breakdownValue: 'Firefox', breakdownType: 'event' },
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

            expect(extractBreakdownValues(tiles)).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event' },
                { breakdownValue: 'Safari', breakdownType: 'event' },
                { breakdownValue: 'Firefox', breakdownType: 'event' },
            ])
        })

        it('orders values by assignment rank, most re-used first', () => {
            const tiles = [
                trendsTile([
                    { action: { order: 0 }, breakdown_value: ['Apple'] },
                    { action: { order: 0 }, breakdown_value: ['Zebra'] },
                ]),
                trendsTile([{ action: { order: 0 }, breakdown_value: ['Zebra'] }]),
            ]

            // Zebra is on two charts vs Apple's one, so the modal lists it first even
            // though it trails the first chart and sorts later as a value
            expect(extractBreakdownValues(tiles)).toEqual([
                { breakdownValue: 'Zebra', breakdownType: 'event' },
                { breakdownValue: 'Apple', breakdownType: 'event' },
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

            expect(extractBreakdownValues(tiles)).toEqual([
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

            expect(extractBreakdownValues(tiles)).toEqual([
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

            expect(extractBreakdownValues(tiles)).toEqual([
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

            expect(extractBreakdownValues(tiles)).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', breakdownProperty: 'event::$browser' },
                { breakdownValue: 'Firefox', breakdownType: 'event', breakdownProperty: 'event::$browser' },
                {
                    breakdownValue: '$$_posthog_breakdown_other_$$',
                    breakdownType: 'event',
                    breakdownProperty: 'event::$browser',
                },
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
            expect(extractBreakdownValues([tile])).toEqual([])
        })

        it('handles cohort breakdowns, keying them all to the shared cohort property', () => {
            const cohortTile = (values: number[][]): DashboardTile<QueryBasedInsightModel> =>
                createTestTile({
                    result: values.map((breakdown_value) => ({ action: { order: 0 }, breakdown_value })),
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            breakdownFilter: {
                                breakdown: values.flat(),
                                breakdown_type: 'cohort',
                            },
                        },
                    } as InsightVizNode<InsightQueryNode>,
                })

            // cohorts 1 and 3 lead their charts and tie, so value order decides; 2 trails its chart
            expect(extractBreakdownValues([cohortTile([[1], [2]]), cohortTile([[3]])])).toEqual([
                { breakdownValue: '1', breakdownType: 'cohort', breakdownProperty: 'cohort' },
                { breakdownValue: '3', breakdownType: 'cohort', breakdownProperty: 'cohort' },
                { breakdownValue: '2', breakdownType: 'cohort', breakdownProperty: 'cohort' },
            ])
        })

        it('unifies single and multi form of one property into one scoped entry', () => {
            const tiles = [
                trendsTile([{ action: { order: 0 }, breakdown_value: ['Chrome'] }], {
                    breakdown: '$browser',
                    breakdown_type: 'event',
                }),
                trendsTile(
                    [
                        { action: { order: 0 }, breakdown_value: ['Chrome'] },
                        { action: { order: 0 }, breakdown_value: ['Firefox'] },
                    ],
                    { breakdowns: [{ property: '$browser' }] }
                ),
            ]

            expect(extractBreakdownValues(tiles)).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', breakdownProperty: 'event::$browser' },
                { breakdownValue: 'Firefox', breakdownType: 'event', breakdownProperty: 'event::$browser' },
            ])
        })

        it('clusters values by property in tile order before ranking within each property', () => {
            const tiles = [
                trendsTile([{ action: { order: 0 }, breakdown_value: ['Mac OS X'] }], { breakdown: '$os' }),
                trendsTile([{ action: { order: 0 }, breakdown_value: ['Mac OS X'] }], { breakdown: '$os' }),
                trendsTile([{ action: { order: 0 }, breakdown_value: ['Chrome'] }], { breakdown: '$browser' }),
                trendsTile([{ action: { order: 0 }, breakdown_value: ['Chrome'] }], { breakdown: '$browser' }),
                trendsTile([{ action: { order: 0 }, breakdown_value: ['Chrome'] }], { breakdown: '$browser' }),
            ]

            // Chrome is on more tiles, but $os tiles come first on the dashboard
            expect(extractBreakdownValues(tiles)).toEqual([
                { breakdownValue: 'Mac OS X', breakdownType: 'event', breakdownProperty: 'event::$os' },
                { breakdownValue: 'Chrome', breakdownType: 'event', breakdownProperty: 'event::$browser' },
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
                    { breakdownValue: 'Chrome', breakdownType: 'event' },
                    { breakdownValue: 'Firefox', breakdownType: 'event' },
                ],
                [{ breakdownValue: 'Chrome', breakdownType: 'event' }],
            ])
        })

        it('keeps the funnel baseline property-less while the funnel values are scoped', () => {
            const tile = createTestTile({
                result: [{ breakdown_value: ['Chrome'] }],
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: { funnelVizType: FunnelVizType.Steps },
                        breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                    },
                } as InsightVizNode<InsightQueryNode>,
            })

            // one baseline pin must keep covering every funnel tile, whatever it breaks down by
            expect(extractBreakdownValuesByTile([tile])).toEqual([
                [
                    { breakdownValue: 'Baseline', breakdownType: 'event' },
                    { breakdownValue: 'Chrome', breakdownType: 'event', breakdownProperty: 'event::$browser' },
                ],
            ])
        })
    })

    describe('groupBreakdownValuesByProperty', () => {
        it('clusters values into property groups, with property-less values last', () => {
            const baseline = { breakdownValue: 'Baseline', breakdownType: 'event' as const }
            const macOs = {
                breakdownValue: 'Mac OS X',
                breakdownType: 'event' as const,
                breakdownProperty: 'event::$os',
            }
            const chrome = {
                breakdownValue: 'Chrome',
                breakdownType: 'event' as const,
                breakdownProperty: 'event::$browser',
            }
            const firefox = {
                breakdownValue: 'Firefox',
                breakdownType: 'event' as const,
                breakdownProperty: 'event::$browser',
            }

            // extractBreakdownValues emits property-less rows first; the modal shows them
            // as the closing section instead, after the property groups in dashboard order
            expect(groupBreakdownValuesByProperty([baseline, macOs, chrome, firefox])).toEqual([
                { breakdownProperty: 'event::$os', values: [macOs] },
                { breakdownProperty: 'event::$browser', values: [chrome, firefox] },
                { values: [baseline] },
            ])
        })
    })

    describe('hasUnresolvedBreakdownTiles', () => {
        const breakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }
        const vizQuery = (source: Record<string, any>): InsightVizNode<InsightQueryNode> =>
            ({ kind: NodeKind.InsightVizNode, source }) as InsightVizNode<InsightQueryNode>

        it.each([
            [
                'trends tile with a breakdown and no results',
                createTestTile({ result: null, query: vizQuery({ kind: NodeKind.TrendsQuery, breakdownFilter }) }),
                true,
            ],
            [
                'trends tile with a breakdown and empty results',
                createTestTile({ result: [], query: vizQuery({ kind: NodeKind.TrendsQuery, breakdownFilter }) }),
                false,
            ],
            [
                'trends tile without a breakdown and no results',
                createTestTile({ result: null, query: vizQuery({ kind: NodeKind.TrendsQuery }) }),
                false,
            ],
            [
                'funnel steps tile with a breakdown and no results',
                createTestTile({
                    result: null,
                    query: vizQuery({
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: { funnelVizType: FunnelVizType.Steps },
                        breakdownFilter,
                    }),
                }),
                true,
            ],
            [
                'time-to-convert funnel tile with a breakdown and no results',
                createTestTile({
                    result: null,
                    query: vizQuery({
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert },
                        breakdownFilter,
                    }),
                }),
                false,
            ],
            [
                'retention tile with a breakdown and no results',
                createTestTile({ result: null, query: vizQuery({ kind: NodeKind.RetentionQuery, breakdownFilter }) }),
                true,
            ],
            [
                'non insight-viz tile with no results',
                createTestTile({ result: null, query: { kind: NodeKind.DataTableNode } as any }),
                false,
            ],
        ])('%s', (_name, tile, expected) => {
            expect(hasUnresolvedBreakdownTiles([tile])).toBe(expected)
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

        it('assigns only values that appear on two or more tiles', () => {
            const result = applyAutoBreakdownColors([[value('Chrome'), value('Firefox')], [value('Chrome')]], [])

            // Firefox is unique to one tile, so it keeps position-based colors instead
            expect(result).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1', source: 'auto' },
            ])
        })

        it('fills free slots in chart order when re-use ties, appending after existing configs', () => {
            const existing: BreakdownColorConfig[] = [
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-3', source: 'manual' },
            ]

            const result = applyAutoBreakdownColors(sharedTiles('Google', 'Alibaba', 'Chrome'), existing)

            // both tiles list Google before Alibaba, so Google leads despite sorting later
            expect(result).toEqual([
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-3', source: 'manual' },
                { breakdownValue: 'Google', breakdownType: 'event', colorToken: 'preset-1', source: 'auto' },
                { breakdownValue: 'Alibaba', breakdownType: 'event', colorToken: 'preset-2', source: 'auto' },
            ])
        })

        it('gives the first slots to the values re-used across the most charts', () => {
            const result = applyAutoBreakdownColors(
                [[value('Apple'), value('Zebra')], [value('Apple'), value('Zebra')], [value('Zebra')]],
                []
            )

            // Zebra is on three charts vs Apple's two, which outranks Apple leading the
            // shared charts and sorting first as a value
            expect(result).toEqual([autoConfig('Zebra', 'preset-1'), autoConfig('Apple', 'preset-2')])
        })

        it("breaks re-use ties by the values' ranking across their own charts", () => {
            const result = applyAutoBreakdownColors(
                [
                    [value('Apple'), value('Zebra')],
                    [value('Zebra'), value('Apple')],
                    [value('Zebra'), value('Apple')],
                ],
                []
            )

            // Zebra leads two of the three charts, so summed across charts it ranks ahead
            // of Apple despite trailing on one chart and sorting first as a value
            expect(result).toEqual([autoConfig('Zebra', 'preset-1'), autoConfig('Apple', 'preset-2')])
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

            // A and Z both lead their charts, so they take the two slots and exhaust the
            // palette; B's own tiles don't show Z's slot, so B reuses it rather than
            // duplicating a color on its own charts
            expect(result).toEqual([
                autoConfig('A', 'preset-1'),
                autoConfig('Z', 'preset-2'),
                autoConfig('B', 'preset-2'),
            ])
        })

        it('re-slots the lower-ranked persisted auto entry of a within-tile collision, in place', () => {
            const existing: BreakdownColorConfig[] = [autoConfig('Bravo', 'preset-1'), autoConfig('Alpha', 'preset-1')]

            const result = applyAutoBreakdownColors(sharedTiles('Alpha', 'Bravo'), existing)

            // both entries came out of the pre-collision-aware wrap; Alpha leads the charts and keeps the slot
            expect(result).toEqual([autoConfig('Bravo', 'preset-2'), autoConfig('Alpha', 'preset-1')])
        })

        it('keeps the entry re-used across more charts when two persisted auto entries collide', () => {
            const existing: BreakdownColorConfig[] = [autoConfig('Alpha', 'preset-1'), autoConfig('Zulu', 'preset-1')]

            const result = applyAutoBreakdownColors(
                [[value('Alpha'), value('Zulu')], [value('Alpha'), value('Zulu')], [value('Zulu')]],
                existing
            )

            // Zulu is shared across more charts, so it keeps its color even though Alpha
            // leads the shared charts and sorts first
            expect(result).toEqual([autoConfig('Alpha', 'preset-2'), autoConfig('Zulu', 'preset-1')])
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

        const scopedValue = (breakdownValue: string, breakdownProperty: string): BreakdownValueAndType => ({
            breakdownValue,
            breakdownType: 'event',
            breakdownProperty,
        })
        const scopedTiles = (breakdownProperty: string, ...breakdownValues: string[]): BreakdownValueAndType[][] => [
            breakdownValues.map((v) => scopedValue(v, breakdownProperty)),
            breakdownValues.map((v) => scopedValue(v, breakdownProperty)),
        ]
        const scopedAutoConfig = (
            breakdownValue: string,
            breakdownProperty: string,
            colorToken: BreakdownColorConfig['colorToken']
        ): BreakdownColorConfig => ({
            breakdownValue,
            breakdownType: 'event',
            breakdownProperty,
            colorToken,
            source: 'auto',
        })

        it('starts each property over from the first palette slot', () => {
            const result = applyAutoBreakdownColors(
                [
                    ...scopedTiles('event::$browser', 'Chrome', 'Firefox'),
                    ...scopedTiles('event::$os', 'Mac OS X', 'Windows'),
                ],
                []
            )

            // properties are independent color worlds like standalone insights: their tiles
            // never meet, so reusing slots across them is invisible and stretches the palette
            expect(result).toEqual([
                scopedAutoConfig('Chrome', 'event::$browser', 'preset-1'),
                scopedAutoConfig('Mac OS X', 'event::$os', 'preset-1'),
                scopedAutoConfig('Firefox', 'event::$browser', 'preset-2'),
                scopedAutoConfig('Windows', 'event::$os', 'preset-2'),
            ])
        })

        it('gives one value the same color under every property it appears under', () => {
            const result = applyAutoBreakdownColors(
                [...scopedTiles('event::is_admin', 'true'), ...scopedTiles('event::is_mobile', 'true')],
                []
            )

            // "true" reads as one value wherever it shows up, so each property keeps its own
            // entry, free to diverge via pinning, but both land on one color
            expect(result).toEqual([
                scopedAutoConfig('true', 'event::is_admin', 'preset-1'),
                scopedAutoConfig('true', 'event::is_mobile', 'preset-1'),
            ])
        })

        it('counts a value on single tiles of two different properties as shared', () => {
            const result = applyAutoBreakdownColors(
                [[scopedValue('true', 'event::is_admin')], [scopedValue('true', 'event::is_mobile')]],
                []
            )

            // one tile each is a value the reader meets twice, and per-property counting is
            // what used to leave it with no dashboard color and a position color that flips
            expect(result).toEqual([
                scopedAutoConfig('true', 'event::is_admin', 'preset-1'),
                scopedAutoConfig('true', 'event::is_mobile', 'preset-1'),
            ])
        })

        it('ranks a value by its charts across properties, so the wider one claims first', () => {
            const result = applyAutoBreakdownColors(
                [
                    [scopedValue('Chrome', 'event::$browser'), scopedValue('Firefox', 'event::$browser')],
                    [scopedValue('Chrome', 'event::$browser'), scopedValue('Firefox', 'event::$browser')],
                    [scopedValue('Firefox', 'event::browser_name')],
                ],
                []
            )

            // Firefox trails Chrome on both $browser charts, but it is on three charts against
            // Chrome's two, so it claims the first slot and carries it into browser_name
            expect(result).toEqual([
                scopedAutoConfig('Firefox', 'event::$browser', 'preset-1'),
                scopedAutoConfig('Firefox', 'event::browser_name', 'preset-1'),
                scopedAutoConfig('Chrome', 'event::$browser', 'preset-2'),
            ])
        })

        it('copies the color a value was pinned to under another property', () => {
            const pin: BreakdownColorConfig = {
                breakdownValue: 'Chrome',
                breakdownType: 'event',
                breakdownProperty: 'event::$browser',
                colorToken: 'preset-6',
                source: 'manual',
            }

            const result = applyAutoBreakdownColors(
                [[scopedValue('Chrome', 'event::$browser')], [scopedValue('Chrome', 'event::browser_name')]],
                [pin]
            )

            // pins claim before auto entries, so the pinned color is the one that spreads
            // instead of the palette's first free slot
            expect(result).toEqual([pin, scopedAutoConfig('Chrome', 'event::browser_name', 'preset-6')])
        })

        it('gives up copying a color when the slot is taken within the other property', () => {
            const pin: BreakdownColorConfig = {
                breakdownValue: 'Opera',
                breakdownType: 'event',
                breakdownProperty: 'event::browser_name',
                colorToken: 'preset-1',
                source: 'manual',
            }

            const result = applyAutoBreakdownColors(
                [
                    [scopedValue('Chrome', 'event::$browser')],
                    [scopedValue('Chrome', 'event::browser_name'), scopedValue('Opera', 'event::browser_name')],
                ],
                [pin]
            )

            // Chrome takes the first slot under $browser, but Opera's pin holds it under
            // browser_name, and sharing a chart with Opera is worse than a second color
            expect(result).toEqual([
                pin,
                scopedAutoConfig('Chrome', 'event::$browser', 'preset-1'),
                scopedAutoConfig('Chrome', 'event::browser_name', 'preset-2'),
            ])
        })

        it('lets a property-less pin cover its value and claim its slot under every property', () => {
            const pin: BreakdownColorConfig = {
                breakdownValue: 'Chrome',
                breakdownType: 'event',
                colorToken: 'preset-1',
                source: 'manual',
            }

            const result = applyAutoBreakdownColors(
                [
                    ...scopedTiles('event::$browser', 'Chrome', 'Firefox'),
                    ...scopedTiles('event::browser_name', 'Chrome', 'Opera'),
                ],
                [pin]
            )

            // the legacy pin matches Chrome under both properties, so neither property
            // assigns Chrome again and both hand out slots around the pinned one
            expect(result).toEqual([
                pin,
                scopedAutoConfig('Firefox', 'event::$browser', 'preset-2'),
                scopedAutoConfig('Opera', 'event::browser_name', 'preset-2'),
            ])
        })

        it('keeps a property-less auto entry covering its value, without a scoped duplicate', () => {
            const legacy = autoConfig('Chrome', 'preset-2')

            const result = applyAutoBreakdownColors(scopedTiles('event::$browser', 'Chrome'), [legacy])

            // dashboards saved before property scoping keep their colors byte-for-byte
            expect(result).toHaveLength(1)
            expect(result[0]).toBe(legacy)
        })

        it('re-slots a displaced property-less auto entry off the slots its tiles already show', () => {
            const existing: BreakdownColorConfig[] = [
                scopedAutoConfig('Alpha', 'event::$browser', 'preset-1'),
                autoConfig('Zulu', 'preset-1'),
            ]

            const result = applyAutoBreakdownColors(scopedTiles('event::$browser', 'Alpha', 'Zulu'), existing)

            // the displaced legacy entry has no property of its own, but its tiles belong to
            // $browser, whose used slots it must avoid to stay distinct on those charts
            expect(result).toEqual([existing[0], autoConfig('Zulu', 'preset-2')])
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

        it('counts a value across the properties it appears under', () => {
            const isShared = buildSharedBreakdownValueLookup([
                [
                    { breakdownValue: 'Chrome', breakdownType: 'event', breakdownProperty: 'event::$browser' },
                    { breakdownValue: 'true', breakdownType: 'event', breakdownProperty: 'event::$browser' },
                ],
                [{ breakdownValue: 'Chrome', breakdownType: 'event', breakdownProperty: 'event::$browser' }],
                [{ breakdownValue: 'true', breakdownType: 'event', breakdownProperty: 'event::is_admin' }],
            ])

            expect(
                isShared({ breakdownValue: 'Chrome', breakdownType: 'event', breakdownProperty: 'event::$browser' })
            ).toBe(true)
            // "true" is on one tile of each of two properties, which is still a value the
            // reader meets twice, so both entries qualify and aim for one color
            expect(
                isShared({ breakdownValue: 'true', breakdownType: 'event', breakdownProperty: 'event::$browser' })
            ).toBe(true)
            expect(
                isShared({ breakdownValue: 'true', breakdownType: 'event', breakdownProperty: 'event::is_admin' })
            ).toBe(true)
            // property-less legacy entries read the same count, wherever the value appears
            expect(isShared({ breakdownValue: 'true', breakdownType: 'event' })).toBe(true)
            expect(isShared({ breakdownValue: 'Chrome', breakdownType: 'event' })).toBe(true)
            // a value on one tile only still keeps its insight's own colors
            expect(
                isShared({ breakdownValue: 'Chrome', breakdownType: 'event', breakdownProperty: 'event::is_admin' })
            ).toBe(false)
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

        it('fills the slots the tile overrides do not use, in position order', () => {
            const tokens = computeTileFallbackTokens(
                [
                    { position: 0, overrideToken: null },
                    { position: 1, overrideToken: 'preset-1' },
                    { position: 2, overrideToken: null },
                    { position: 3, overrideToken: 'preset-4' },
                    { position: 4, overrideToken: null },
                ],
                15
            )

            expect(tokens).toEqual(
                new Map([
                    [0, 'preset-2'],
                    [2, 'preset-3'],
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

        it('keeps scoped and property-less entries for one value separate, deduplicating within each scope', () => {
            const scopedPin: BreakdownColorConfig = {
                breakdownValue: 'Chrome',
                breakdownType: 'event',
                breakdownProperty: 'event::$browser',
                colorToken: 'preset-2',
                source: 'manual',
            }

            const merged = mergeBreakdownColorConfigs(
                [scopedPin],
                [
                    { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1' },
                    { ...scopedPin, colorToken: 'preset-3' },
                ]
            )

            // the scoped pin shadows its persisted version but not the legacy one, which
            // still colors Chrome under other properties
            expect(merged).toEqual([
                scopedPin,
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1' },
            ])
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

        it('prefers a property-scoped entry and falls back to a property-less one', () => {
            const scopedConfigs: BreakdownColorConfig[] = [
                { breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1' },
                {
                    breakdownValue: 'Chrome',
                    breakdownType: 'event',
                    breakdownProperty: 'event::$browser',
                    colorToken: 'preset-2',
                },
            ]

            // the scoped entry wins for its own property even though the legacy one is listed first
            expect(findBreakdownColorConfig(scopedConfigs, 'Chrome', 'event', 'event::$browser')?.colorToken).toBe(
                'preset-2'
            )
            // under any other property, and without property context, the legacy entry applies
            expect(findBreakdownColorConfig(scopedConfigs, 'Chrome', 'event', 'event::browser_name')?.colorToken).toBe(
                'preset-1'
            )
            expect(findBreakdownColorConfig(scopedConfigs, 'Chrome', 'event')?.colorToken).toBe('preset-1')
        })
    })
})
