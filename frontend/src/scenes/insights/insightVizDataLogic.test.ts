import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { ChartDisplayType, InsightShortId } from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { useMocks } from '~/mocks/jest'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { trendsQueryDefault, funnelsQueryDefault } from '~/queries/nodes/InsightQuery/defaults'
import { NodeKind } from '~/queries/schema'
import { FunnelLayout } from 'lib/constants'

const Insight123 = '123' as InsightShortId

describe('insightVizDataLogic', () => {
    let builtInsightVizDataLogic: ReturnType<typeof insightVizDataLogic.build>
    let builtInsightDataLogic: ReturnType<typeof insightDataLogic.build>
    let builtFeatureFlagLogic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/insights/trend': [],
            },
        })
        initKeaTests()

        builtFeatureFlagLogic = featureFlagLogic()
        builtFeatureFlagLogic.mount()

        const props = { dashboardItemId: Insight123 }

        builtInsightVizDataLogic = insightVizDataLogic(props)
        builtInsightDataLogic = insightDataLogic(props)

        builtInsightDataLogic.mount()
        builtInsightVizDataLogic.mount()
    })

    describe('updateQuerySource', () => {
        it('updates the query source', () => {
            // with default query
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({ filterTestAccounts: true })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        filterTestAccounts: true,
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.querySource).toMatchObject({ filterTestAccounts: true })

            // merges with existing changes
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateQuerySource({ samplingFactor: 0.1 })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        filterTestAccounts: true,
                        samplingFactor: 0.1,
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.querySource).toEqual({
                ...trendsQueryDefault,
                filterTestAccounts: true,
                samplingFactor: 0.1,
            })
        })
    })

    describe('updateDateRange', () => {
        it('updates the date range', () => {
            // when dateRange is empty
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateDateRange({
                    date_from: '-7d',
                    date_to: null,
                })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        dateRange: {
                            date_from: '-7d',
                            date_to: null,
                        },
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.dateRange).toEqual({
                date_from: '-7d',
                date_to: null,
            })

            // merges with existing dateRange
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateDateRange({
                    date_to: '-3d',
                })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        dateRange: {
                            date_from: '-7d',
                            date_to: '-3d',
                        },
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.dateRange).toEqual({
                date_from: '-7d',
                date_to: '-3d',
            })
        })
    })

    describe('updateBreakdown', () => {
        it('updates the breakdown', () => {
            // when breakdown is empty
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateBreakdown({
                    breakdown_type: 'event',
                    breakdown: '$current_url',
                })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        breakdown: {
                            breakdown_type: 'event',
                            breakdown: '$current_url',
                        },
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.breakdown).toEqual({
                breakdown_type: 'event',
                breakdown: '$current_url',
            })

            // merges with existing breakdown
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateBreakdown({
                    breakdown: '$browser',
                })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        breakdown: {
                            breakdown_type: 'event',
                            breakdown: '$browser',
                        },
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.breakdown).toEqual({
                breakdown_type: 'event',
                breakdown: '$browser',
            })
        })
    })

    describe('updateInsightFilter', () => {
        it('updates the insight filter', () => {
            // when insight filter is empty
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateInsightFilter({ display: ChartDisplayType.ActionsAreaGraph })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        trendsFilter: {
                            display: 'ActionsAreaGraph',
                        },
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.insightFilter).toEqual({ display: 'ActionsAreaGraph' })

            // merges with existing insight filter
            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateInsightFilter({
                    show_values_on_series: true,
                })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...trendsQueryDefault,
                        trendsFilter: {
                            display: 'ActionsAreaGraph',
                            show_values_on_series: true,
                        },
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.insightFilter).toEqual({
                display: 'ActionsAreaGraph',
                show_values_on_series: true,
            })
        })

        it('updates the insight filter for other insight query kinds', () => {
            builtInsightVizDataLogic.actions.updateQuerySource(funnelsQueryDefault)

            expectLogic(builtInsightDataLogic, () => {
                builtInsightVizDataLogic.actions.updateInsightFilter({
                    layout: FunnelLayout.horizontal,
                })
            }).toMatchValues({
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        ...funnelsQueryDefault,
                        funnelsFilter: {
                            ...funnelsQueryDefault.funnelsFilter,
                            layout: FunnelLayout.horizontal,
                        },
                        trendsFilter: {}, // we currently don't remove insight filters of previous query kinds
                    },
                },
            })

            expect(builtInsightVizDataLogic.values.insightFilter).toMatchObject({
                ...funnelsQueryDefault.funnelsFilter,
                layout: FunnelLayout.horizontal,
            })
        })
    })
})
