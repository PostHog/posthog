import { expectLogic } from 'kea-test-utils'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    BaseMathType,
    ChartDisplayType,
    CompareLabelType,
    InsightLogicProps,
    InsightModel,
    PropertyMathType,
} from '~/types'

import { AggregationType, compareResultKey, insightsTableDataLogic } from './insightsTableDataLogic'

describe('insightsTableDataLogic', () => {
    let logic: ReturnType<typeof insightsTableDataLogic.build>

    describe('with dashboardItemId', () => {
        const props: InsightLogicProps = { dashboardItemId: '123' as any }

        beforeEach(() => {
            initKeaTests()
            logic = insightsTableDataLogic(props)
            logic.mount()
        })

        describe('allowAggregation', () => {
            it('allows for trends table insight', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsTable,
                    },
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    allowAggregation: true,
                })
            })

            it('allows with only total volume entities', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview' },
                        { kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount },
                        { kind: NodeKind.EventsNode, event: '$pageview', math: PropertyMathType.Sum },
                    ],
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    allowAggregation: true,
                })
            })

            it('disallows with other math type entities', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.UniqueUsers }],
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    allowAggregation: false,
                })
            })
        })

        describe('aggregation', () => {
            it('by default averages for insights with unique math entity', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.UniqueUsers }],
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    aggregation: AggregationType.Average,
                })
            })

            it('by default totals for insights without unique math entity', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    aggregation: AggregationType.Total,
                })
            })

            it('sets aggregation type', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
                    trendsFilter: {},
                }

                const vizLogic = insightVizDataLogic(props)
                vizLogic.mount()

                vizLogic.actions.updateQuerySource(query)

                await expectLogic(vizLogic, () => {
                    logic.actions.setDetailedResultsAggregationType(AggregationType.Median)
                }).toFinishAllListeners()

                await expectLogic(logic).toMatchValues({
                    aggregation: AggregationType.Median,
                })
            })
        })
    })

    describe('compareResultKey', () => {
        const makeResult = (overrides: Partial<IndexedTrendResult>): IndexedTrendResult =>
            ({
                action: { order: 0 },
                label: '$pageview',
                breakdown_value: '',
                ...overrides,
            }) as IndexedTrendResult

        it.each([
            [
                'distinguishes by action order',
                makeResult({ action: { order: 0 } as any }),
                makeResult({ action: { order: 1 } as any }),
                false,
            ],
            [
                'distinguishes by breakdown value',
                makeResult({ breakdown_value: 'Chrome' }),
                makeResult({ breakdown_value: 'Firefox' }),
                false,
            ],
            [
                'distinguishes by label when order and breakdown match',
                makeResult({ label: '$pageview' }),
                makeResult({ label: '$autocapture' }),
                false,
            ],
            [
                'matches when all fields are the same',
                makeResult({ action: { order: 0 } as any, label: '$pageview', breakdown_value: 'Chrome' }),
                makeResult({ action: { order: 0 } as any, label: '$pageview', breakdown_value: 'Chrome' }),
                true,
            ],
            [
                'does not collide when underscore appears in label vs breakdown',
                makeResult({ label: 'a_b', breakdown_value: 'c' }),
                makeResult({ label: 'a', breakdown_value: 'b_c' }),
                false,
            ],
        ])('%s', (_name, a, b, shouldMatch) => {
            if (shouldMatch) {
                expect(compareResultKey(a)).toEqual(compareResultKey(b))
            } else {
                expect(compareResultKey(a)).not.toEqual(compareResultKey(b))
            }
        })

        it('produces valid JSON array string', () => {
            const result = compareResultKey(
                makeResult({ action: { order: 2 } as any, label: 'test', breakdown_value: 'val' })
            )
            expect(JSON.parse(result)).toEqual([2, 'test', 'val'])
        })

        it('handles nullish fields gracefully', () => {
            const result = compareResultKey(
                makeResult({ action: undefined, label: undefined, breakdown_value: undefined } as any)
            )
            expect(JSON.parse(result)).toEqual([0, '', ''])
        })
    })

    describe('compare selectors', () => {
        const props: InsightLogicProps = { dashboardItemId: undefined }
        let builtDataNodeLogic: ReturnType<typeof dataNodeLogic.build>

        const makeCompareResult = (overrides: Partial<IndexedTrendResult>): Partial<IndexedTrendResult> => ({
            action: {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                math_group_type_index: null,
                properties: {},
            } as any,
            label: '$pageview',
            count: 100,
            data: [10, 20, 30],
            labels: ['day1', 'day2', 'day3'],
            days: ['2023-01-01', '2023-01-02', '2023-01-03'],
            breakdown_value: '',
            persons_urls: [],
            ...overrides,
        })

        beforeEach(async () => {
            initKeaTests(false)

            builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
            builtDataNodeLogic.mount()
            await expectLogic(dataNodeLogic).toFinishAllListeners()

            insightDataLogic(props).mount()
            insightVizDataLogic(props).mount()
            trendsDataLogic(props).mount()

            logic = insightsTableDataLogic(props)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('returns all results and empty map when compare is off', async () => {
            const insight: Partial<InsightModel> = {
                result: [makeCompareResult({})],
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                previousResultMap: new Map(),
            })

            expect(logic.values.displayResults).toHaveLength(1)
            expect(logic.values.getPreviousResult(logic.values.indexedResults[0])).toBeUndefined()
        })

        it('filters displayResults to current-only when compare is on', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                compareFilter: { compare: true },
            }
            const insight: Partial<InsightModel> = {
                result: [
                    makeCompareResult({ compare_label: CompareLabelType.Current, compare: true }),
                    makeCompareResult({ compare_label: CompareLabelType.Previous, compare: true }),
                ],
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(props)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                compareFilter: { compare: true },
            })

            expect(logic.values.indexedResults).toHaveLength(2)
            expect(logic.values.displayResults).toHaveLength(1)
            expect(logic.values.displayResults[0].compare_label).toBe('current')
        })

        it('builds previousResultMap keyed by compareResultKey', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview' },
                    { kind: NodeKind.EventsNode, event: '$autocapture' },
                ],
                compareFilter: { compare: true },
            }
            const insight: Partial<InsightModel> = {
                result: [
                    makeCompareResult({ compare_label: CompareLabelType.Current, compare: true }),
                    makeCompareResult({
                        compare_label: CompareLabelType.Previous,
                        compare: true,
                        count: 80,
                        data: [8, 16, 24],
                    }),
                    makeCompareResult({
                        compare_label: CompareLabelType.Current,
                        compare: true,
                        action: { order: 1, id: '$autocapture', name: '$autocapture' } as any,
                        label: '$autocapture',
                    }),
                    makeCompareResult({
                        compare_label: CompareLabelType.Previous,
                        compare: true,
                        action: { order: 1, id: '$autocapture', name: '$autocapture' } as any,
                        label: '$autocapture',
                        count: 60,
                        data: [6, 12, 18],
                    }),
                ],
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(props)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            expect(logic.values.previousResultMap.size).toBe(2)
            expect(logic.values.displayResults).toHaveLength(2)
            expect(logic.values.displayResults.every((r: IndexedTrendResult) => r.compare_label === 'current')).toBe(
                true
            )
        })

        it('getPreviousResult matches current items to their previous counterparts', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                compareFilter: { compare: true },
            }
            const insight: Partial<InsightModel> = {
                result: [
                    makeCompareResult({ compare_label: CompareLabelType.Current, compare: true, count: 100 }),
                    makeCompareResult({ compare_label: CompareLabelType.Previous, compare: true, count: 80 }),
                ],
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(props)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            const currentItem = logic.values.displayResults[0]
            const previousItem = logic.values.getPreviousResult(currentItem)
            expect(previousItem).not.toBeUndefined()
            expect(previousItem!.compare_label).toBe('previous')
            expect(previousItem!.count).toBe(80)
        })
    })
})
