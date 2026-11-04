import { MOCK_USER_UUID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { liveDashboardIds } from 'scenes/dashboard/liveDashboardIds'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightsApi } from 'scenes/insights/utils/api'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AppContext,
    DashboardBasicType,
    DashboardType,
    InsightShortId,
    InsightModel,
    UserBasicType,
} from '~/types'

import * as dashboardsApi from 'products/dashboards/frontend/generated/api'

import { addToDashboardModalLogic } from './addToDashboardModalLogic'

const Insight1 = '1' as InsightShortId

const MOCK_INSIGHT: InsightModel = {
    id: 1,
    short_id: Insight1,
    name: 'Test Insight',
    query: {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: 'total' }],
        },
    },
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
} as InsightModel

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
                '/api/environments/:team_id/insights/:id': async ({ request }) => {
                    const payload = (await request.json()) as Record<string, any>
                    return [200, { ...MOCK_INSIGHT, ...payload }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
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

    it('addDashboardSuccess sets navigation target and adds the insight to the new dashboard', async () => {
        jest.spyOn(dashboardsApi, 'dashboardsAddInsightCreate').mockResolvedValue({ id: 5, dashboard_id: 99 })
        logic = addToDashboardModalLogic({ dashboardItemId: Insight1 })
        logic.mount()

        const newDashboard = {
            id: 99,
            name: 'New Dashboard',
            tiles: [],
        } as unknown as DashboardType

        await expectLogic(logic, () => {
            dashboardsModel.actions.addDashboardSuccess(newDashboard)
        })
            .toDispatchActions(['setDashboardToNavigateTo', 'addToDashboard', 'addInsightToDashboard'])
            .toMatchValues({
                _dashboardToNavigateTo: 99,
            })
            // Let addInsightToDashboard settle before afterEach unmounts the logics it touches
            .toFinishAllListeners()
    })

    it.each([
        {
            name: 'adding places the insight on the dashboard and keeps the others',
            change: (modal: ReturnType<typeof addToDashboardModalLogic.build>) => modal.actions.addToDashboard(4),
            endpoint: 'dashboardsAddInsightCreate' as const,
            expectedRequest: [4, { insight_id: 1 }],
            expectedDashboards: [1, 2, 4],
        },
        {
            name: 'removing deletes the tile on that dashboard and keeps the others',
            change: (modal: ReturnType<typeof addToDashboardModalLogic.build>) => modal.actions.removeFromDashboard(2),
            endpoint: 'dashboardsDeleteTile' as const,
            expectedRequest: [2, { tile_id: 12 }],
            expectedDashboards: [1],
        },
    ])('$name', async ({ change, endpoint, expectedRequest, expectedDashboards }) => {
        const updateSpy = jest.spyOn(api.insights, 'update')
        jest.spyOn(dashboardsApi, 'dashboardsAddInsightCreate').mockResolvedValue({ id: 14, dashboard_id: 4 })
        jest.spyOn(dashboardsApi, 'dashboardsDeleteTile').mockResolvedValue()
        jest.spyOn(insightsApi, 'getByNumericId').mockResolvedValue({
            ...MOCK_INSIGHT,
            dashboard_tiles: expectedDashboards.map((dashboardId) => ({
                id: 10 + dashboardId,
                dashboard_id: dashboardId,
            })),
        })
        const insightProps = { dashboardItemId: Insight1 }
        const insightLog = insightLogic(insightProps)
        insightLog.mount()
        // The mount loads the insight, and that load must not land after the change below.
        await expectLogic(insightLog).toFinishAllListeners()
        insightLog.actions.loadInsightSuccess({
            ...MOCK_INSIGHT,
            dashboard_tiles: [
                { id: 11, dashboard_id: 1 },
                { id: 12, dashboard_id: 2 },
                { id: 13, dashboard_id: 3, deleted: true },
            ],
        })

        logic = addToDashboardModalLogic(insightProps)
        logic.mount()

        await expectLogic(logic, () => change(logic)).toFinishAllListeners()

        expect(dashboardsApi[endpoint]).toHaveBeenCalledWith(expect.any(String), ...expectedRequest)
        expect(updateSpy).not.toHaveBeenCalled()
        expect(liveDashboardIds(insightLog.values.insight.dashboard_tiles)).toEqual(expectedDashboards)
    })

    it('orders dashboards: on insight first, then mine, then others pinned, then the rest', async () => {
        const insightOnlyOnDash2: InsightModel = {
            ...MOCK_INSIGHT,
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
                '/api/environments/:team_id/insights/:id': async ({ request }) => {
                    const payload = (await request.json()) as Record<string, any>
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
        const insightOnlyOnDash2: InsightModel = {
            ...MOCK_INSIGHT,
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
                '/api/environments/:team_id/insights/:id': async ({ request }) => {
                    const payload = (await request.json()) as Record<string, any>
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
        const insightOnlyOnDash2: InsightModel = {
            ...MOCK_INSIGHT,
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
                '/api/environments/:team_id/insights/:id': async ({ request }) => {
                    const payload = (await request.json()) as Record<string, any>
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
