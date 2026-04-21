jest.mock('~/queries/query', () => ({
    __esModule: true,
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn().mockResolvedValue({ result: [] }),
}))

import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { useMocks } from '~/mocks/jest'
import { examples } from '~/queries/examples'
import { performQuery } from '~/queries/query'
import {
    FunnelsQuery,
    InsightVizNode,
    NodeKind,
    ResultCustomizationBy,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelVizType, InsightShortId } from '~/types'

import { insightDataLogic } from './insightDataLogic'

const mockedPerformQuery = performQuery as jest.MockedFunction<typeof performQuery>

const Insight123 = '123' as InsightShortId

describe('insightDataLogic', () => {
    let theInsightDataLogic: ReturnType<typeof insightDataLogic.build>
    let theInsightLogic: ReturnType<typeof insightLogic.build>
    let theFeatureFlagLogic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
            },
        })
        initKeaTests()

        const props = { dashboardItemId: Insight123 }
        theFeatureFlagLogic = featureFlagLogic()
        theFeatureFlagLogic.mount()

        theInsightDataLogic = insightDataLogic(props)
        theInsightDataLogic.mount()

        theInsightLogic = insightLogic(props)
        theInsightLogic.mount()
    })

    describe('syncQueryFromProps', () => {
        const funnelsSource: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview' },
                { kind: NodeKind.EventsNode, event: '$pageleave' },
            ],
            funnelsFilter: { funnelVizType: FunnelVizType.Steps },
        }

        const stepsQuery: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: funnelsSource,
        }

        const trendsQuery: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: { ...funnelsSource, funnelsFilter: { funnelVizType: FunnelVizType.Trends } },
        }

        it('updates internalQuery without triggering setQuery listeners', async () => {
            const adHocProps = {
                dashboardItemId: 'new-AdHoc.InsightViz.test-node' as any,
                query: stepsQuery,
            }

            const adHocLogic = insightDataLogic(adHocProps)
            adHocLogic.mount()

            await expectLogic(adHocLogic, () => {
                adHocLogic.actions.syncQueryFromProps(trendsQuery)
            })
                .toDispatchActions(['syncQueryFromProps'])
                .toNotHaveDispatchedActions(['setQuery'])
                .toMatchValues({
                    internalQuery: trendsQuery,
                    query: trendsQuery,
                })
        })

        it('propsChanged syncs query when props.query changes', async () => {
            const adHocProps = {
                dashboardItemId: 'new-AdHoc.InsightViz.test-node' as any,
                query: stepsQuery,
            }

            const adHocLogic = insightDataLogic(adHocProps)
            adHocLogic.mount()

            await expectLogic(adHocLogic).toMatchValues({ query: stepsQuery })

            // Rebuild with updated props triggers propsChanged
            insightDataLogic({ ...adHocProps, query: trendsQuery })

            await expectLogic(adHocLogic)
                .toDispatchActions(['syncQueryFromProps'])
                .toNotHaveDispatchedActions(['setQuery'])
                .toMatchValues({ query: trendsQuery })
        })

        it('does not dispatch syncQueryFromProps when query is unchanged', async () => {
            const adHocProps = {
                dashboardItemId: 'new-AdHoc.InsightViz.test-node' as any,
                query: stepsQuery,
            }

            const adHocLogic = insightDataLogic(adHocProps)
            adHocLogic.mount()

            // Rebuild with same query
            insightDataLogic({ ...adHocProps, query: { ...stepsQuery } })

            await expectLogic(adHocLogic).toNotHaveDispatchedActions(['syncQueryFromProps'])
        })
    })

    describe('cached insight query sync', () => {
        const baseQuery = examples.InsightTrends as InsightVizNode
        const trendsSource = baseQuery.source as TrendsQuery
        const buildLocalUpdatedQuery = (): InsightVizNode => ({
            ...baseQuery,
            source: {
                ...trendsSource,
                trendsFilter: {
                    ...trendsSource.trendsFilter,
                    resultCustomizations: {
                        series_0: {
                            assignmentBy: ResultCustomizationBy.Value,
                            hidden: true,
                        },
                    },
                },
            },
        })

        it('does not reset local query when cachedInsight query is unchanged', async () => {
            const localUpdatedQuery = buildLocalUpdatedQuery()
            const logic = insightDataLogic({
                dashboardItemId: Insight123,
                cachedInsight: { short_id: Insight123, query: baseQuery } as any,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setQuery(localUpdatedQuery)
            }).toMatchValues({ query: localUpdatedQuery })

            await expectLogic(logic, () => {
                insightDataLogic({
                    dashboardItemId: Insight123,
                    cachedInsight: { short_id: Insight123, query: { ...baseQuery } } as any,
                    loadPriority: 1,
                }).mount()
            }).toMatchValues({ query: localUpdatedQuery })
        })

        it('syncs local query when cachedInsight query changes', async () => {
            const localUpdatedQuery = buildLocalUpdatedQuery()
            const updatedCachedQuery: InsightVizNode = {
                ...baseQuery,
                source: {
                    ...baseQuery.source,
                    dateRange: {
                        ...baseQuery.source.dateRange,
                        date_from: '-14d',
                    },
                },
            }

            const logic = insightDataLogic({
                dashboardItemId: Insight123,
                cachedInsight: { short_id: Insight123, query: baseQuery } as any,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setQuery(localUpdatedQuery)
            }).toMatchValues({ query: localUpdatedQuery })

            await expectLogic(logic, () => {
                insightDataLogic({
                    dashboardItemId: Insight123,
                    cachedInsight: { short_id: Insight123, query: updatedCachedQuery } as any,
                    loadPriority: 1,
                }).mount()
            }).toMatchValues({ query: updatedCachedQuery })
        })
    })

    describe('reacts when the insight changes', () => {
        const q = examples.InsightTrends

        it('sets query when override is set', async () => {
            await expectLogic(theInsightDataLogic, () => {
                theInsightLogic.actions.setInsight({ query: q }, { overrideQuery: true })
            })
                .toDispatchActions(['setQuery'])
                .toMatchValues({
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            breakdownFilter: {
                                breakdown: '$geoip_country_code',
                                breakdown_type: 'event',
                            },
                            dateRange: {
                                date_from: '-7d',
                            },
                            filterTestAccounts: false,
                            interval: 'day',
                            kind: NodeKind.TrendsQuery,
                            properties: {
                                type: 'AND',
                                values: [
                                    {
                                        type: 'OR',
                                        values: [
                                            {
                                                key: '$current_url',
                                                operator: 'exact',
                                                type: 'event',
                                                value: ['https://hedgebox.net/files/'],
                                            },
                                            {
                                                key: '$geoip_country_code',
                                                operator: 'exact',
                                                type: 'event',
                                                value: ['US', 'AU'],
                                            },
                                        ],
                                    },
                                ],
                            },
                            series: [
                                {
                                    custom_name: 'Views',
                                    event: '$pageview',
                                    kind: 'EventsNode',
                                    name: '$pageview',
                                    properties: [
                                        {
                                            key: '$browser',
                                            operator: 'exact',
                                            type: 'event',
                                            value: 'Chrome',
                                        },
                                        {
                                            key: 'id',
                                            type: 'cohort',
                                            operator: 'in',
                                            value: 2,
                                        },
                                    ],
                                },
                            ],
                            trendsFilter: {
                                display: 'ActionsAreaGraph',
                            },
                            version: 2,
                        },
                    },
                })
        })
        it('does not set query override is not set', async () => {
            await expectLogic(theInsightDataLogic, () => {
                theInsightLogic.actions.setInsight({ query: q }, { overrideQuery: false })
            }).toNotHaveDispatchedActions(['setQuery'])
        })
    })

    describe('dashboard tile: cached insight with no chart data yet', () => {
        beforeEach(() => {
            mockedPerformQuery.mockClear()
        })

        it('dispatches loadData when dashboardId is set and result is null', async () => {
            const logic = insightDataLogic({
                dashboardItemId: Insight123,
                dashboardId: 99,
                cachedInsight: {
                    short_id: Insight123,
                    query: examples.InsightTrends,
                    result: null,
                } as any,
            })
            // dataNode in tests does not receive query/cachedResults via BindLogic; the loader may bail
            // before performQuery. We only assert that insightDataLogic kicks a force loadData.
            await expectLogic(logic, () => {
                logic.mount()
            }).toDispatchActions(['loadData'])
            logic.unmount()
        })

        it('does not dispatch loadData when not on a dashboard', async () => {
            const logic = insightDataLogic({
                dashboardItemId: Insight123,
                cachedInsight: {
                    short_id: Insight123,
                    query: examples.InsightTrends,
                    result: null,
                } as any,
            })
            await expectLogic(logic, () => {
                logic.mount()
            }).toNotHaveDispatchedActions(['loadData'])

            await expectLogic(logic).delay(0)
            expect(mockedPerformQuery).not.toHaveBeenCalled()
            logic.unmount()
        })

        it('does not dispatch loadData when result is already present (empty series)', async () => {
            const logic = insightDataLogic({
                dashboardItemId: Insight123,
                dashboardId: 99,
                cachedInsight: {
                    short_id: Insight123,
                    query: examples.InsightTrends,
                    result: [],
                } as any,
            })
            await expectLogic(logic, () => {
                logic.mount()
            }).toNotHaveDispatchedActions(['loadData'])

            await expectLogic(logic).delay(0)
            expect(mockedPerformQuery).not.toHaveBeenCalled()
            logic.unmount()
        })

        it('does not dispatch loadData when doNotLoad is true', async () => {
            const logic = insightDataLogic({
                dashboardItemId: Insight123,
                dashboardId: 99,
                doNotLoad: true,
                cachedInsight: {
                    short_id: Insight123,
                    query: examples.InsightTrends,
                    result: null,
                } as any,
            })
            await expectLogic(logic, () => {
                logic.mount()
            }).toNotHaveDispatchedActions(['loadData'])

            await expectLogic(logic).delay(0)
            expect(mockedPerformQuery).not.toHaveBeenCalled()
            logic.unmount()
        })

        it('does not dispatch loadData for web analytics web stats tile', async () => {
            const logic = insightDataLogic({
                dashboardItemId: Insight123,
                dashboardId: 99,
                cachedInsight: {
                    short_id: Insight123,
                    query: examples.WebAnalyticsPath,
                    result: null,
                } as any,
            })
            await expectLogic(logic, () => {
                logic.mount()
            }).toNotHaveDispatchedActions(['loadData'])

            await expectLogic(logic).delay(0)
            expect(mockedPerformQuery).not.toHaveBeenCalled()
            logic.unmount()
        })
    })
})
