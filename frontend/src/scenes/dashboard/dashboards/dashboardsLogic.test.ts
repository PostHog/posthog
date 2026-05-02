import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic, truth } from 'kea-test-utils'

import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'
import { AppContext, DashboardType, UserBasicType } from '~/types'

import dashboardJson from '../__mocks__/dashboard.json'

let dashboardId = 1234
const dashboard = (extras: Partial<DashboardType>): DashboardType => {
    dashboardId = dashboardId + 1
    return {
        ...dashboardJson,
        id: dashboardId,
        name: 'Test dashboard: ' + dashboardId,
        ...extras,
    } as any as DashboardType
}

const blankScene = (): any => ({ scene: { component: () => null, logic: null } })
const scenes: any = { [Scene.Dashboards]: blankScene }

describe('dashboardsLogic', () => {
    let logic: ReturnType<typeof dashboardsLogic.build>

    const allDashboards = [
        { ...dashboard({ created_by: { uuid: 'USER_UUID' } as UserBasicType, is_shared: true }) },
        { ...dashboard({ created_by: { uuid: 'USER_UUID' } as UserBasicType, pinned: true }) },
        { ...dashboard({ created_by: { uuid: 'user2' } as UserBasicType, pinned: true }) },
        {
            ...dashboard({
                created_by: { uuid: 'USER_UUID' } as UserBasicType,
                is_shared: true,
                pinned: true,
            }),
        },
        { ...dashboard({ created_by: { uuid: 'USER_UUID' } as UserBasicType }) },
        { ...dashboard({ created_by: { uuid: 'user2' } as UserBasicType, name: 'needle' }) },
        {
            ...dashboard({
                created_by: { uuid: 'USER_UUID' } as UserBasicType,
                name: 'VMS Feature - History Browser - Nova',
            }),
        },
    ]

    beforeEach(async () => {
        window.POSTHOG_APP_CONTEXT = { current_user: MOCK_DEFAULT_USER } as unknown as AppContext

        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': {
                    count: 7,
                    next: null,
                    previous: null,
                    results: allDashboards,
                },
            },
        })

        initKeaTests()

        dashboardsModel.mount()
        await expectLogic(dashboardsModel).toDispatchActions(['loadDashboardsSuccess'])
        sceneLogic({ scenes }).mount()
        sceneLogic.actions.setTabs([
            { id: '1', title: '...', pathname: '/', search: '', hash: '', active: true, iconType: 'blank' },
        ])

        logic = dashboardsLogic({ tabId: '1' })
        logic.mount()
    })

    it('shows all dashboards when no filters', async () => {
        expect(logic.values.dashboards).toHaveLength(allDashboards.length)
    })

    it('shows correct dashboards when on pinned tab', async () => {
        expectLogic(logic, () => {
            logic.actions.setCurrentTab(DashboardsTab.Pinned)
        }).toMatchValues({
            dashboards: truth((dashboards: DashboardType[]) => {
                return dashboards.length === 3 && dashboards.every((d) => d.pinned)
            }),
        })
    })

    it('shows correct dashboards when on my tab', async () => {
        expectLogic(logic, () => {
            logic.actions.setCurrentTab(DashboardsTab.Yours)
        }).toMatchValues({
            dashboards: truth((dashboards: DashboardType[]) => {
                return dashboards.length === 5 && dashboards.every((d) => d.created_by?.uuid === 'USER_UUID')
            }),
        })
    })

    it('shows correct dashboards when filtering by name', async () => {
        expectLogic(logic, () => {
            logic.actions.setFilters({ createdBy: 'user2' })
        }).toMatchValues({
            dashboards: truth((dashboards: DashboardType[]) => {
                return (
                    dashboards.length === 2 &&
                    dashboards[0].created_by?.uuid === 'user2' &&
                    dashboards[1].created_by?.uuid === 'user2'
                )
            }),
        })
    })

    it('shows correct dashboards when filtering by name and shared', async () => {
        expectLogic(logic, () => {
            logic.actions.setFilters({ createdBy: 'user2', shared: true })
        }).toMatchValues({
            dashboards: [],
        })
    })

    it('shows correct dashboards when filtering by name and on pinned tab', async () => {
        expectLogic(logic, () => {
            logic.actions.setCurrentTab(DashboardsTab.Pinned)
            logic.actions.setFilters({ createdBy: 'user2' })
        }).toMatchValues({
            dashboards: truth((dashboards: DashboardType[]) => {
                return dashboards.length === 1 && dashboards[0].pinned
            }),
        })
    })

    it('shows correct dashboards filtering by shared and on pinned tab', async () => {
        expectLogic(logic, () => {
            logic.actions.setCurrentTab(DashboardsTab.Pinned)
            logic.actions.setFilters({ shared: true })
        }).toMatchValues({
            dashboards: truth((dashboards: DashboardType[]) => {
                return (
                    dashboards.length === 1 &&
                    dashboards.every((d) => d.pinned && d.is_shared) &&
                    dashboards[0].created_by?.uuid === 'USER_UUID'
                )
            }),
        })
    })

    it('shows correct dashboards when searching by name', async () => {
        expectLogic(logic, () => {
            logic.actions.setCurrentTab(DashboardsTab.Pinned)
            logic.actions.setFilters({ shared: true })
        }).toMatchValues({
            dashboards: truth((dashboards: DashboardType[]) => {
                return (
                    dashboards.length === 1 &&
                    dashboards.every((d) => d.pinned && d.is_shared) &&
                    dashboards[0].created_by?.uuid === 'USER_UUID'
                )
            }),
        })
    })

    it('uses server-side search results when a search term is set', async () => {
        // Search is executed server-side (Postgres trigram word similarity); the logic
        // delegates ranking to the API and uses the returned list as-is. We mock the search
        // endpoint and assert the selector swaps the in-memory list for the response.
        const needleDashboard = allDashboards.find((d) => d.name === 'needle')!
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': (req) => {
                    if (req.url.searchParams.get('search')) {
                        return [200, { count: 1, next: null, previous: null, results: [needleDashboard] }]
                    }
                    return [200, { count: 7, next: null, previous: null, results: allDashboards }]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.setSearch('needl')
        }).toDispatchActions(['loadSearchedDashboardsSuccess'])

        expect(logic.values.dashboards).toHaveLength(1)
        expect(logic.values.dashboards[0].name).toBe('needle')
    })

    it('does not refetch when only pinned / shared / createdBy change', async () => {
        // Pinned/shared/createdBy stay client-side over the in-memory list — only search
        // and tags drive the server fetch. (Tag changes only refetch when a search is
        // active; that's covered by a separate test below.)
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': () => {
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.setFilters({ pinned: true })
            logic.actions.setFilters({ shared: true })
            logic.actions.setFilters({ createdBy: 'someone-uuid' })
        }).toNotHaveDispatchedActions(['loadSearchedDashboards'])
    })

    it('sends tag filters to the server alongside search', async () => {
        // Server-side tag filtering keeps MCP/API clients in sync with the UI and ensures
        // the limit:200 cap operates on the right population (pre-tag-filtered, not post).
        let lastRequestUrl: URL | null = null
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': (req) => {
                    lastRequestUrl = req.url
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.setFilters({ tags: ['finance', 'q4'] })
            logic.actions.setSearch('sales')
        }).toDispatchActions(['loadSearchedDashboardsSuccess'])

        expect(lastRequestUrl).not.toBeNull()
        expect(lastRequestUrl!.searchParams.get('search')).toBe('sales')
        expect(lastRequestUrl!.searchParams.getAll('tags')).toEqual(['finance', 'q4'])
    })

    it('refetches when tags change while a search is active', async () => {
        let requestCount = 0
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': () => {
                    requestCount += 1
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.setSearch('sales')
        }).toDispatchActions(['loadSearchedDashboardsSuccess'])
        const afterSearch = requestCount

        await expectLogic(logic, () => {
            logic.actions.setFilters({ tags: ['finance'] })
        }).toDispatchActions(['loadSearchedDashboardsSuccess'])

        expect(requestCount).toBe(afterSearch + 1)
    })

    it('syncs search to URL when setSearch is called', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSearch('needle')
        })

        expect(router.values.searchParams.search).toBe('needle')
    })

    it('removes search param from URL when search is cleared', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSearch('needle')
        })

        await expectLogic(logic, () => {
            logic.actions.setSearch('')
        })

        expect(router.values.searchParams.search).toBeUndefined()
    })

    it('loads search from URL into filters on mount', async () => {
        // Recreate logic with URL containing a search param
        logic.unmount()
        router.actions.push(urls.dashboards(), { search: 'needle' })
        logic = dashboardsLogic({ tabId: '1' })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            filters: expect.objectContaining({ search: 'needle' }),
        })
    })

    it('loads search from URL when the router coerces it to a number', async () => {
        logic.unmount()
        router.actions.push(urls.dashboards(), { search: 33333333 as unknown as string })
        logic = dashboardsLogic({ tabId: '1' })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            filters: expect.objectContaining({ search: '33333333' }),
        })
    })
})
