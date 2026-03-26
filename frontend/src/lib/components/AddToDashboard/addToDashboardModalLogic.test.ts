import { MOCK_USER_UUID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { queryFromFilters } from '~/queries/nodes/InsightViz/utils'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AppContext,
    DashboardBasicType,
    DashboardType,
    InsightShortId,
    InsightType,
    QueryBasedInsightModel,
    UserBasicType,
} from '~/types'

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

const OTHER_USER_UUID = 'other-user-uuid'

const mkDashboard = (
    id: number,
    name: string,
    pinned: boolean,
    createdByUuid: string | null = null
): DashboardBasicType => ({
    id,
    name,
    description: '',
    pinned,
    created_at: '2021-01-01T00:00:00.000Z',
    created_by: createdByUuid ? ({ uuid: createdByUuid } as UserBasicType) : null,
    last_accessed_at: null,
    last_viewed_at: null,
    is_shared: false,
    deleted: false,
    creation_mode: 'default',
    user_access_level: AccessControlLevel.Editor,
})

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
        // Tests may set `current_user: null`; clear so the next test gets a fresh `initKeaTests` bootstrap.
        delete window.POSTHOG_APP_CONTEXT
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

    it('orders dashboards: on insight first, then mine, then others pinned, then the rest', async () => {
        const insightOnlyOnDash2: QueryBasedInsightModel = {
            ...MOCK_INSIGHT,
            dashboards: [2],
            dashboard_tiles: [{ dashboard_id: 2 }] as any,
        }
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': {
                    results: [insightOnlyOnDash2],
                },
                '/api/environments/:team_id/dashboards/': {
                    results: [
                        mkDashboard(1, 'Pinned other', true, OTHER_USER_UUID),
                        mkDashboard(2, 'Current mine', false, MOCK_USER_UUID),
                        mkDashboard(3, 'Mine unpinned', false, MOCK_USER_UUID),
                        mkDashboard(4, 'Other unpinned', false, OTHER_USER_UUID),
                    ],
                },
            },
            patch: {
                '/api/environments/:team_id/insights/:id': async (req) => {
                    const payload = await req.json()
                    return [200, { ...insightOnlyOnDash2, ...payload }]
                },
            },
        })
        initKeaTests()

        const dashboards = dashboardsModel()
        dashboards.mount()
        await expectLogic(dashboards, () => {
            dashboards.actions.loadDashboards()
        }).toFinishAllListeners()

        const insightProps = { dashboardItemId: Insight1 }
        const insightLog = insightLogic(insightProps)
        insightLog.mount()
        insightLog.actions.loadInsightSuccess(insightOnlyOnDash2)

        logic = addToDashboardModalLogic(insightProps)
        logic.mount()

        await expectLogic(logic).toMatchValues({
            orderedDashboards: [
                expect.objectContaining({ id: 2 }),
                expect.objectContaining({ id: 3 }),
                expect.objectContaining({ id: 1 }),
                expect.objectContaining({ id: 4 }),
            ],
        })
    })

    it('when user is not loaded, dashboards with no creator are not grouped as mine', async () => {
        window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
        const insightOnlyOnDash2: QueryBasedInsightModel = {
            ...MOCK_INSIGHT,
            dashboards: [2],
            dashboard_tiles: [{ dashboard_id: 2 }] as any,
        }
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': {
                    results: [insightOnlyOnDash2],
                },
                '/api/environments/:team_id/dashboards/': {
                    results: [
                        mkDashboard(2, 'Current', false, MOCK_USER_UUID),
                        mkDashboard(1, 'No creator', false, null),
                        mkDashboard(3, 'Other', false, OTHER_USER_UUID),
                    ],
                },
            },
            patch: {
                '/api/environments/:team_id/insights/:id': async (req) => {
                    const payload = await req.json()
                    return [200, { ...insightOnlyOnDash2, ...payload }]
                },
            },
        })
        initKeaTests()

        const dashboards = dashboardsModel()
        dashboards.mount()
        await expectLogic(dashboards, () => {
            dashboards.actions.loadDashboards()
        }).toFinishAllListeners()

        const insightProps = { dashboardItemId: Insight1 }
        const insightLog = insightLogic(insightProps)
        insightLog.mount()
        insightLog.actions.loadInsightSuccess(insightOnlyOnDash2)

        logic = addToDashboardModalLogic(insightProps)
        logic.mount()

        await expectLogic(logic).toMatchValues({
            orderedDashboards: [
                expect.objectContaining({ id: 2 }),
                expect.objectContaining({ id: 1 }),
                expect.objectContaining({ id: 3 }),
            ],
        })
    })

    it('places mine pinned in the mine bucket before others pinned', async () => {
        const insightOnlyOnDash2: QueryBasedInsightModel = {
            ...MOCK_INSIGHT,
            dashboards: [2],
            dashboard_tiles: [{ dashboard_id: 2 }] as any,
        }
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': {
                    results: [insightOnlyOnDash2],
                },
                '/api/environments/:team_id/dashboards/': {
                    results: [
                        mkDashboard(2, 'Current', false, MOCK_USER_UUID),
                        mkDashboard(3, 'Unpinned mine', false, MOCK_USER_UUID),
                        mkDashboard(4, 'Pinned mine', true, MOCK_USER_UUID),
                        mkDashboard(5, 'Other pinned', true, OTHER_USER_UUID),
                    ],
                },
            },
            patch: {
                '/api/environments/:team_id/insights/:id': async (req) => {
                    const payload = await req.json()
                    return [200, { ...insightOnlyOnDash2, ...payload }]
                },
            },
        })
        initKeaTests()

        const dashboards = dashboardsModel()
        dashboards.mount()
        await expectLogic(dashboards, () => {
            dashboards.actions.loadDashboards()
        }).toFinishAllListeners()

        const insightProps = { dashboardItemId: Insight1 }
        const insightLog = insightLogic(insightProps)
        insightLog.mount()
        insightLog.actions.loadInsightSuccess(insightOnlyOnDash2)

        logic = addToDashboardModalLogic(insightProps)
        logic.mount()

        await expectLogic(logic).toMatchValues({
            orderedDashboards: [
                expect.objectContaining({ id: 2 }),
                expect.objectContaining({ id: 4 }),
                expect.objectContaining({ id: 3 }),
                expect.objectContaining({ id: 5 }),
            ],
        })
    })
})
