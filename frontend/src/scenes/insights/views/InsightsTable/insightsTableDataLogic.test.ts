import { expectLogic } from 'kea-test-utils'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, InsightShortId, PropertyMathType } from '~/types'

import { AggregationType, compareResultKey, insightsTableDataLogic } from './insightsTableDataLogic'

const Insight123 = '123' as InsightShortId

describe('insightsTableDataLogic', () => {
    let logic: ReturnType<typeof insightsTableDataLogic.build>

    const props = { dashboardItemId: Insight123 }
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

            // Make sure insightVizDataLogic is mounted
            const vizLogic = insightVizDataLogic(props)
            vizLogic.mount()

            vizLogic.actions.updateQuerySource(query)

            // Wait for the async updateInsightFilter to complete
            await expectLogic(vizLogic, () => {
                logic.actions.setDetailedResultsAggregationType(AggregationType.Median)
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                aggregation: AggregationType.Median,
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
        ])('%s', (_name, a, b, shouldMatch) => {
            if (shouldMatch) {
                expect(compareResultKey(a)).toEqual(compareResultKey(b))
            } else {
                expect(compareResultKey(a)).not.toEqual(compareResultKey(b))
            }
        })
    })
})
