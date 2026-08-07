import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardBasicType } from '~/types'

import { dashboardsModel, mergeTileTextUpdatesIntoDashboard, nameCompareFunction } from './dashboardsModel'

const dashboards: Partial<DashboardBasicType>[] = [
    {
        id: 1,
        name: 'Generated Dashboard: 123',
    },
    {
        id: 2,
        name: 'Generated Dashboard: 456',
    },
    {
        id: 3,
        name: 'Dashboard: 789',
    },
    {
        id: 4,
        name: 'Generated Dashboard: 101',
    },
    {
        id: 5,
        name: 'Dashboard: 112',
    },
    {
        id: 6,
        name: 'Dashboard: 131',
    },
    {
        id: 7,
    },
    {
        id: 8,
        name: 'k',
    },
    {
        id: 9,
        name: 'Pinned Later',
        pinned: true,
        last_viewed_at: '2024-05-02T12:00:00Z',
    },
    {
        id: 10,
        name: 'Pinned Never',
        pinned: true,
        last_viewed_at: null,
    },
    {
        id: 11,
        name: 'Pinned Earlier',
        pinned: true,
        last_viewed_at: '2024-04-30T12:00:00Z',
    },
]

const basicDashboard: DashboardBasicType = {
    id: 1,
    name: '',
    description: 'This is not a generated dashboard',
    pinned: false,
    created_at: new Date().toISOString(),
    created_by: null,
    last_accessed_at: null,
    last_viewed_at: null,
    is_shared: false,
    deleted: false,
    creation_mode: 'default',
    user_access_level: AccessControlLevel.Editor,
}

describe('the dashboards model', () => {
    let logic: ReturnType<typeof dashboardsModel.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': () => {
                    return [
                        200,
                        {
                            count: dashboards.length,
                            results: dashboards,
                            next: undefined,
                        },
                    ]
                },
            },
        })

        initKeaTests()
        logic = dashboardsModel()
        logic.mount()
    })

    describe('sorting dashboards', () => {
        it('can sort dashboards correctly', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadDashboards()
            })
                .toDispatchActions(['loadDashboardsSuccess'])
                .toMatchValues({
                    nameSortedDashboards: [
                        {
                            id: 11,
                            last_viewed_at: '2024-04-30T12:00:00Z',
                            name: 'Pinned Earlier',
                            pinned: true,
                        },
                        {
                            id: 9,
                            last_viewed_at: '2024-05-02T12:00:00Z',
                            name: 'Pinned Later',
                            pinned: true,
                        },
                        {
                            id: 10,
                            last_viewed_at: null,
                            name: 'Pinned Never',
                            pinned: true,
                        },
                        {
                            id: 5,
                            name: 'Dashboard: 112',
                        },
                        {
                            id: 6,
                            name: 'Dashboard: 131',
                        },
                        {
                            id: 3,
                            name: 'Dashboard: 789',
                        },
                        {
                            id: 8,
                            name: 'k',
                        },
                        {
                            id: 7,
                        },
                    ],
                })
        })

        it('compares names correctly', async () => {
            const generatedDashboardA = { ...basicDashboard, id: 1, name: 'Generated Dashboard: XYZ' }
            const untitledDashboard = { ...basicDashboard, id: 2, name: 'Untitled' }
            const randomDashboard = { ...basicDashboard, id: 3, name: 'Random' }
            const randomDashboard2 = { ...basicDashboard, id: 3, name: 'Too Random' }
            expect(nameCompareFunction(generatedDashboardA, untitledDashboard)).toEqual(-1)
            expect(nameCompareFunction(untitledDashboard, generatedDashboardA)).toEqual(1)
            expect(nameCompareFunction(generatedDashboardA, randomDashboard)).toEqual(-1)
            expect(nameCompareFunction(randomDashboard, generatedDashboardA)).toEqual(1)
            expect(nameCompareFunction(generatedDashboardA, randomDashboard2)).toEqual(-1)
            expect(nameCompareFunction(randomDashboard2, generatedDashboardA)).toEqual(1)

            expect(nameCompareFunction(untitledDashboard, randomDashboard)).toEqual(1)
            expect(nameCompareFunction(randomDashboard, untitledDashboard)).toEqual(-1)
            expect(nameCompareFunction(untitledDashboard, randomDashboard2)).toEqual(1)
            expect(nameCompareFunction(randomDashboard2, untitledDashboard)).toEqual(-1)

            expect(nameCompareFunction(randomDashboard2, randomDashboard)).toEqual(1)
            expect(nameCompareFunction(randomDashboard, randomDashboard2)).toEqual(-1)
        })

        it('sorts pinned dashboards by last viewed time', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadDashboards()
            })
                .toDispatchActions(['loadDashboardsSuccess'])
                .toMatchValues({
                    pinnedDashboards: [
                        expect.objectContaining({ id: 9 }),
                        expect.objectContaining({ id: 11 }),
                        expect.objectContaining({ id: 10 }),
                    ],
                })
        })
    })

    it('clears primary_dashboard from team when deleting the primary dashboard', async () => {
        const primaryDashboardId = 42
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, primary_dashboard: primaryDashboardId })
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': {
                    count: 0,
                    results: [],
                },
            },
            patch: {
                '/api/environments/:team_id/dashboards/:id/': {
                    id: primaryDashboardId,
                    name: 'My Dashboard',
                    deleted: true,
                },
            },
        })
        logic = dashboardsModel()
        logic.mount()

        logic.actions.deleteDashboard({ id: primaryDashboardId, deleteInsights: false })

        await expectLogic(logic).toDispatchActions(['deleteDashboardSuccess'])
        await expectLogic(teamLogic).toMatchValues({
            currentTeam: expect.objectContaining({ primary_dashboard: null }),
        })
    })

    it('replaces the cache on a first-page load so a refetch evicts stale rows', async () => {
        // Drain the mount-time load, which seeds the cache with the full mock list.
        await expectLogic(logic).toDispatchActions(['loadDashboardsSuccess'])
        expect(logic.values.nameSortedDashboards.length).toBeGreaterThan(1)

        // A refetch whose first page no longer contains those rows must drop them. The old merge-only reducer
        // kept every row for the whole session, so a dashboard deleted elsewhere never disappeared on refetch.
        await expectLogic(logic, () => {
            logic.actions.loadDashboardsSuccess({
                count: 1,
                next: null,
                previous: null,
                results: [{ id: 5, name: 'Only survivor' } as any],
            })
        }).toMatchValues({ nameSortedDashboards: [expect.objectContaining({ id: 5, name: 'Only survivor' })] })
    })

    it('drops the row instead of dead-ending when deleting an already-gone dashboard', async () => {
        const ghostId = 7
        await expectLogic(logic)
            .toDispatchActions(['loadDashboardsSuccess'])
            .toMatchValues({ nameSortedDashboards: expect.arrayContaining([expect.objectContaining({ id: ghostId })]) })

        // The dashboard is already deleted server-side, so the PATCH 404s. The delete should still resolve and
        // drop the ghost row rather than raising deleteDashboardFailure and trapping the user behind a red toast.
        useMocks({
            patch: {
                '/api/environments/:team_id/dashboards/:id/': () => [404, { detail: 'Not found' }],
            },
        })
        await expectLogic(logic, () => {
            logic.actions.deleteDashboard({ id: ghostId, deleteInsights: false })
        })
            .toDispatchActions(['deleteDashboardSuccess', 'delayedDeleteDashboard'])
            .toNotHaveDispatchedActions(['deleteDashboardFailure'])
        expect(logic.values.rawDashboards[ghostId]).toBeUndefined()
    })

    it('does not clear primary_dashboard when deleting a non-primary dashboard', async () => {
        const primaryDashboardId = 42
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, primary_dashboard: primaryDashboardId })
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': {
                    count: 0,
                    results: [],
                },
            },
            patch: {
                '/api/environments/:team_id/dashboards/:id/': {
                    id: 99,
                    name: 'Other Dashboard',
                    deleted: true,
                },
            },
        })
        logic = dashboardsModel()
        logic.mount()

        logic.actions.deleteDashboard({ id: 99, deleteInsights: false })

        await expectLogic(logic).toDispatchActions(['deleteDashboardSuccess'])
        await expectLogic(teamLogic).toMatchValues({
            currentTeam: expect.objectContaining({ primary_dashboard: primaryDashboardId }),
        })
    })
})

describe('mergeTileTextUpdatesIntoDashboard', () => {
    it('updates only text body and preserves server metadata', () => {
        const dashboard = {
            id: 123,
            tiles: [
                {
                    id: 1,
                    text: {
                        body: 'server body',
                        last_modified_at: '2026-03-17T10:00:00Z',
                    },
                },
            ],
        } as any

        const merged = mergeTileTextUpdatesIntoDashboard(dashboard, [
            {
                id: 1,
                text: {
                    body: 'client body',
                    last_modified_at: 'stale-client-value',
                },
            },
        ])

        expect(merged.tiles?.[0]?.text?.body).toEqual('client body')
        expect(merged.tiles?.[0]?.text?.last_modified_at).toEqual('2026-03-17T10:00:00Z')
    })
})
