import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { useMocks } from '~/mocks/jest'
import { examples } from '~/queries/examples'
import { FunnelsQuery, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelVizType, InsightShortId } from '~/types'

import { insightDataLogic } from './insightDataLogic'

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
})
