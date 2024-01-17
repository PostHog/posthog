import { expectLogic } from 'kea-test-utils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { useMocks } from '~/mocks/jest'
import { examples } from '~/queries/examples'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { NodeKind, TrendsQuery } from '~/queries/schema'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

import { insightDataLogic } from './insightDataLogic'

const Insight123 = '123' as InsightShortId

describe('insightDataLogic', () => {
    let theInsightDataLogic: ReturnType<typeof insightDataLogic.build>
    let theInsightLogic: ReturnType<typeof insightLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/insights/trend': [],
            },
        })
        initKeaTests()
    })

    describe('reacts when the insight changes', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(() => {
            theInsightDataLogic = insightDataLogic(props)
            theInsightDataLogic.mount()

            theInsightLogic = insightLogic(props)
            theInsightLogic.mount()
        })

        it('sets query when present', async () => {
            const q = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*'],
                    after: '-24h',
                    limit: 100,
                },
            }

            await expectLogic(theInsightDataLogic, () => {
                theInsightLogic.actions.setInsight({ query: q }, {})
            })
                .toDispatchActions(['setQuery'])
                .toMatchValues({
                    query: q,
                })
        })

        it('sets query when filters is present and override is set', async () => {
            const q = examples.InsightTrendsQuery as TrendsQuery

            const filters = queryNodeToFilter(q)

            await expectLogic(theInsightDataLogic, () => {
                theInsightLogic.actions.setInsight({ filters }, { overrideFilter: true })
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
                                    math: 'total',
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
                                            value: 2,
                                        },
                                    ],
                                },
                            ],
                            trendsFilter: {
                                display: 'ActionsAreaGraph',
                            },
                        },
                    },
                })
        })
        it('does not set query when filters is present and override is not set', async () => {
            const q = examples.InsightTrendsQuery as TrendsQuery

            const filters = queryNodeToFilter(q)

            await expectLogic(theInsightDataLogic, () => {
                theInsightLogic.actions.setInsight({ filters }, { overrideFilter: false })
            }).toNotHaveDispatchedActions(['setQuery'])
        })
        it('does not set query when insight is invalid', async () => {
            await expectLogic(theInsightDataLogic, () => {
                theInsightLogic.actions.setInsight({ filters: {}, query: undefined }, {})
            }).toNotHaveDispatchedActions(['setQuery'])
        })
    })
})
