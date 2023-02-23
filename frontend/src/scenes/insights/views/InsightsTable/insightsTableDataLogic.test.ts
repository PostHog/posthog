import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { BaseMathType, ChartDisplayType, InsightShortId, PropertyMathType } from '~/types'
import { NodeKind, TrendsQuery } from '~/queries/schema'

import { insightsTableDataLogic, AggregationType } from './insightsTableDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

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

            insightDataLogic(props).actions.updateQuerySource(query)

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

            insightDataLogic(props).actions.updateQuerySource(query)

            await expectLogic(logic).toMatchValues({
                allowAggregation: true,
            })
        })

        it('disallows with other math type entities', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.UniqueUsers }],
            }

            insightDataLogic(props).actions.updateQuerySource(query)

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

            insightDataLogic(props).actions.updateQuerySource(query)

            await expectLogic(logic).toMatchValues({
                aggregation: AggregationType.Average,
            })
        })

        it('by default totals for insights without unique math entity', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
            }

            insightDataLogic(props).actions.updateQuerySource(query)

            await expectLogic(logic).toMatchValues({
                aggregation: AggregationType.Total,
            })
        })

        it('sets aggregation type', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
            }

            insightDataLogic(props).actions.updateQuerySource(query)

            await expectLogic(logic, () => {
                logic.actions.setAggregationType(AggregationType.Median)
            }).toMatchValues({
                aggregation: AggregationType.Median,
            })
        })
    })
})
