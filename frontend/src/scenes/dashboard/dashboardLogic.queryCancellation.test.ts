import { expectLogic, partial } from 'kea-test-utils'
import api from 'lib/api'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { now } from 'lib/dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { boxToString, dashboardResult, insightOnDashboard, tileFromInsight } from 'scenes/dashboard/dashboardLogic.test'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { initKeaTests } from '~/test/init'
import { DashboardType, InsightModel, InsightShortId } from '~/types'

const seenQueryIDs: string[] = []

describe('dashboardLogic query cancellation', () => {
    let logic: ReturnType<typeof dashboardLogic.build>

    let dashboards: Record<number, DashboardType> = {}

    let dashboardTwelveInsightLoadedCount = 0

    beforeEach(() => {
        jest.spyOn(api, 'update')

        const insights: Record<number, InsightModel> = {
            2040: {
                ...insightOnDashboard(2040, [12]),
                id: 2040,
                short_id: '2040' as InsightShortId,
                last_refresh: now().toISOString(),
            },
        }
        dashboards = {
            12: {
                ...dashboardResult(12, [tileFromInsight(insights['2040'])]),
            },
        }
        useMocks({
            get: {
                '/api/projects/:team/dashboards/12/': { ...dashboards['12'] },
                '/api/projects/:team/dashboards/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [{ ...dashboards['12'] }],
                },
                '/api/projects/:team/insights/:id/': (req, _res, ctx) => {
                    const clientQueryId = req.url.searchParams.get('client_query_id')
                    if (clientQueryId !== null) {
                        seenQueryIDs.push(clientQueryId)
                    }

                    const dashboard = req.url.searchParams.get('from_dashboard')
                    if (!dashboard) {
                        throw new Error('the logic must always add this param')
                    }
                    const matched = insights[boxToString(req.params['id'])]
                    if (!matched) {
                        return [404, null]
                    }
                    if (dashboard === '12') {
                        dashboardTwelveInsightLoadedCount++
                        // delay for 2 seconds before response without pausing
                        // but only the first time that dashboard 12 refreshes its results
                        if (dashboardTwelveInsightLoadedCount === 1) {
                            return [ctx.status(200), ctx.delay(2000), ctx.json(matched)]
                        }
                    }
                    return [200, matched]
                },
            },
            post: {
                '/api/projects/:team/insights/cancel/': [201],
            },
            patch: {
                '/api/projects/:team/dashboards/:id/': async (req) => {
                    const dashboardId = typeof req.params['id'] === 'string' ? req.params['id'] : req.params['id'][0]
                    const payload = await req.json()
                    return [200, { ...dashboards[dashboardId], ...payload }]
                },
                '/api/projects/:team/insights/:id/': async (req) => {
                    try {
                        const updates = await req.json()
                        if (typeof updates !== 'object') {
                            return [500, `this update should receive an object body not ${JSON.stringify(updates)}`]
                        }
                        const insightId = boxToString(req.params.id)

                        const starting: InsightModel = insights[insightId]
                        insights[insightId] = {
                            ...starting,
                            ...updates,
                        }

                        starting.dashboards?.forEach((dashboardId) => {
                            // remove this insight from any dashboard it is already on
                            dashboards[dashboardId].tiles = dashboards[dashboardId].tiles.filter(
                                (t) => !!t.insight && t.insight.id !== starting.id
                            )
                        })

                        insights[insightId].dashboards?.forEach((dashboardId: number) => {
                            // then add it to any it new references
                            dashboards[dashboardId].tiles.push(tileFromInsight(insights[insightId]))
                        })

                        return [200, insights[insightId]]
                    } catch (e) {
                        return [500, e]
                    }
                },
            },
        })
        initKeaTests()
        dashboardsModel.mount()
        insightsModel.mount()
    })

    describe('cancelling queries', () => {
        beforeEach(async () => {
            logic = dashboardLogic({ id: 12 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('cancels a running query', async () => {
            jest.spyOn(api, 'create')

            setTimeout(() => {
                // this change of filters will dispatch cancellation on the first query
                // will run while the -180d query is still running
                logic.actions.setDates('-90d', null)
            }, 200)
            // dispatches an artificially slow data request
            // takes 3000 milliseconds to return
            logic.actions.setDates('-180d', null)

            await expectLogic(logic)
                .toDispatchActions([
                    'setDates',
                    'updateFilters',
                    'abortAnyRunningQuery',
                    'refreshAllDashboardItems',
                    'abortAnyRunningQuery',
                    'setDates',
                    'updateFilters',
                    'abortAnyRunningQuery',
                    'abortQuery',
                    'refreshAllDashboardItems',
                    eventUsageLogic.actionTypes.reportDashboardRefreshed,
                ])
                .toMatchValues({
                    filters: partial({ date_from: '-90d' }),
                })

            const mockCreateCalls = (api.create as jest.Mock).mock.calls
            // there will be at least two used client query ids
            // the most recent has not been cancelled
            // the one before that has been
            // the query IDs are made of `${dashboard query ID}::{insight query ID}`
            // only the dashboard query ID is sent to the API
            const cancelledQueryID = seenQueryIDs[seenQueryIDs.length - 2].split('::')[0]
            expect(mockCreateCalls).toEqual([
                [
                    `api/projects/${MOCK_TEAM_ID}/insights/cancel`,
                    {
                        client_query_id: cancelledQueryID,
                    },
                ],
            ])
        })
    })
})
