jest.mock('~/queries/query', () => ({
    __esModule: true,
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn().mockResolvedValue({ result: [] }),
}))

import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { useMocks } from '~/mocks/jest'
import { insightsModel } from '~/models/insightsModel'
import { examples } from '~/queries/examples'
import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import { performQuery } from '~/queries/query'
import {
    FunnelsQuery,
    InsightVizNode,
    NodeKind,
    ResultCustomizationBy,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelVizType, InsightShortId, InsightType } from '~/types'

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

    describe('queryChanged', () => {
        const tracesQuery = {
            kind: NodeKind.InsightVizNode,
            source: { kind: NodeKind.TracesQuery },
        } as unknown as InsightVizNode

        const doubleWrappedDataVisualizationQuery = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.DataVisualizationNode,
                source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
            },
        } as unknown as InsightVizNode

        it.each([
            ['TracesQuery', tracesQuery],
            ['DataVisualizationNode', doubleWrappedDataVisualizationQuery],
        ])('treats an InsightVizNode wrapping an unsupported %s source as changed', async (_, query) => {
            await expectLogic(theInsightDataLogic, () => {
                theInsightDataLogic.actions.setQuery(query)
            }).toMatchValues({ queryChanged: true })
        })

        it('treats the default query of a supported source kind as unchanged', async () => {
            const defaultTrendsQuery = getDefaultQuery(
                InsightType.TRENDS,
                theInsightDataLogic.values.filterTestAccountsDefault
            )
            await expectLogic(theInsightDataLogic, () => {
                theInsightDataLogic.actions.setQuery(defaultTrendsQuery)
            }).toMatchValues({ queryChanged: false })
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

        // On a dashboard tile, `setQuery` is shared with insightVizDataLogic, whose listener calls
        // props.setQuery (persistDisplayOptions). If a tile re-render re-syncs the incoming cached
        // query via setQuery, it loops back into a PATCH of that (stale) query, reverting a display
        // option the user just saved. propsChanged must use syncQueryFromProps on dashboard tiles.
        it('syncs a changed cached query via syncQueryFromProps, not setQuery, on a dashboard tile', async () => {
            const localUpdatedQuery = buildLocalUpdatedQuery()
            const staleCachedQuery: InsightVizNode = {
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
                dashboardId: 99,
                cachedInsight: { short_id: Insight123, query: baseQuery } as any,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setQuery(localUpdatedQuery)
            }).toMatchValues({ query: localUpdatedQuery })

            await expectLogic(logic, () => {
                insightDataLogic({
                    dashboardItemId: Insight123,
                    dashboardId: 99,
                    cachedInsight: { short_id: Insight123, query: staleCachedQuery } as any,
                    loadPriority: 1,
                }).mount()
            })
                .toDispatchActions(['syncQueryFromProps'])
                .toNotHaveDispatchedActions(['setQuery'])
                .toMatchValues({ query: staleCachedQuery })
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

    describe('persistDisplayOptions', () => {
        const insightId = 42
        const Insight42 = '42' as InsightShortId
        const baseQuery: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: { kind: NodeKind.TrendsQuery, series: [] },
        }
        const updatedQuery: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: { kind: NodeKind.TrendsQuery, series: [], trendsFilter: { showLegend: true } as any },
        }

        let logic: ReturnType<typeof insightDataLogic.build>
        let patchSpy: jest.Mock

        beforeEach(() => {
            patchSpy = jest.fn().mockResolvedValue([200, { id: insightId, short_id: Insight42, query: updatedQuery }])
            useMocks({
                patch: { '/api/environments/:team_id/insights/:id': patchSpy },
            })

            const props = {
                dashboardItemId: Insight42,
                cachedInsight: { id: insightId, short_id: Insight42, query: baseQuery } as any,
            }
            insightsModel.mount()
            insightLogic(props).mount()
            logic = insightDataLogic(props)
            logic.mount()
        })

        it('debounces and fires renameInsightSuccess on success', async () => {
            await expectLogic(logic, () => {
                logic.actions.persistDisplayOptions(updatedQuery)
            })
                .toFinishAllListeners()
                .toDispatchActions(['renameInsightSuccess'])

            expect(patchSpy).toHaveBeenCalledTimes(1)
        })

        it('collapses multiple rapid dispatches into a single PATCH', async () => {
            await expectLogic(logic, () => {
                logic.actions.persistDisplayOptions(updatedQuery)
                logic.actions.persistDisplayOptions(updatedQuery)
                logic.actions.persistDisplayOptions(updatedQuery)
            })
                .toFinishAllListeners()
                .toDispatchActions(['renameInsightSuccess'])

            expect(patchSpy).toHaveBeenCalledTimes(1)
        })

        it('skips the PATCH when the query is unchanged from the saved insight', async () => {
            await expectLogic(logic, () => {
                logic.actions.persistDisplayOptions(baseQuery)
            }).toFinishAllListeners()

            expect(patchSpy).not.toHaveBeenCalled()
        })

        it('skips the PATCH while this insight is being edited in the insight scene', async () => {
            // Editing an insight opened from a dashboard reuses the tile's keyed logic, which wired
            // persistDisplayOptions as props.setQuery. The scene must persist only via explicit save.
            sceneLogic.mount()
            sceneLogic.actions.setScene(Scene.Insight, undefined, {} as any)
            const findMountedSpy = jest.spyOn(insightSceneLogic, 'findMounted').mockReturnValue({
                values: { insightLogicRef: { logic: { key: Insight42 } } },
            } as any)

            try {
                await expectLogic(logic, () => {
                    logic.actions.persistDisplayOptions(updatedQuery)
                }).toFinishAllListeners()

                expect(patchSpy).not.toHaveBeenCalled()
            } finally {
                findMountedSpy.mockRestore()
                sceneLogic.unmount()
            }
        })
    })
})
