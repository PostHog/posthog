import { expectLogic } from 'kea-test-utils'

import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { queryFromFilters } from '~/queries/nodes/InsightViz/utils'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType, InsightShortId, InsightType, QueryBasedInsightModel } from '~/types'

import { addToDashboardModalLogic } from './addToDashboardModalLogic'

const Insight1 = '1' as InsightShortId

const MOCK_INSIGHT: QueryBasedInsightModel = {
    id: 1,
    short_id: Insight1,
    name: 'Test Insight',
    query: queryFromFilters({ insight: InsightType.TRENDS, events: [{ id: '$pageview' }] }),
    dashboards: [1, 2],
    dashboard_tiles: [{ dashboard_id: 1 }, { dashboard_id: 2 }] as any,
    result: ['result'],
    saved: true,
    order: null,
    last_refresh: null,
    created_at: '2021-01-01T00:00:00.000Z',
    created_by: null,
    deleted: false,
    description: '',
    is_sample: false,
    is_shared: null,
    pinned: null,
    refresh_interval: null,
    updated_at: '2021-01-01T00:00:00.000Z',
    updated_by: null,
    visibility: null,
    last_modified_at: '2021-01-01T00:00:00.000Z',
    last_modified_by: null,
    layouts: {},
    color: null,
    user_access_level: AccessControlLevel.Editor,
} as QueryBasedInsightModel

describe('addToDashboardModalLogic', () => {
    let logic: ReturnType<typeof addToDashboardModalLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': {
                    results: [MOCK_INSIGHT],
                },
                '/api/environments/:team_id/dashboards/': {
                    results: [],
                },
            },
            patch: {
                '/api/environments/:team_id/insights/:id': async (req) => {
                    const payload = await req.json()
                    return [200, { ...MOCK_INSIGHT, ...payload }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('addNewDashboard sets redirectAfterCreation to false on newDashboardLogic', async () => {
        logic = addToDashboardModalLogic({ dashboardItemId: Insight1 })
        logic.mount()

        logic.actions.addNewDashboard()

        await expectLogic(newDashboardLogic)
            .toDispatchActions(['showNewDashboardModal', 'setRedirectAfterCreation'])
            .toMatchValues({
                redirectAfterCreation: false,
            })
    })

    it('addDashboardSuccess sets navigation target and triggers insight update', async () => {
        logic = addToDashboardModalLogic({ dashboardItemId: Insight1 })
        logic.mount()

        const newDashboard = {
            id: 99,
            name: 'New Dashboard',
            tiles: [],
        } as unknown as DashboardType<QueryBasedInsightModel>

        await expectLogic(logic, () => {
            dashboardsModel.actions.addDashboardSuccess(newDashboard)
        })
            .toDispatchActions(['setDashboardToNavigateTo', 'addToDashboard', 'updateInsight'])
            .toMatchValues({
                _dashboardToNavigateTo: 99,
            })
    })
})
