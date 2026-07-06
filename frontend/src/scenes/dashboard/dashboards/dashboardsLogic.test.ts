import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic, truth } from 'kea-test-utils'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DashboardsFilters, DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
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

    const CURRENT_USER = { id: 178, uuid: 'USER_UUID' } as UserBasicType
    const OTHER_USER = { id: 2, uuid: 'user2' } as UserBasicType

    const allDashboards = [
        { ...dashboard({ created_by: CURRENT_USER, is_shared: true }) },
        { ...dashboard({ created_by: CURRENT_USER, pinned: true }) },
        { ...dashboard({ created_by: OTHER_USER, pinned: true }) },
        {
            ...dashboard({
                created_by: CURRENT_USER,
                is_shared: true,
                pinned: true,
            }),
        },
        { ...dashboard({ created_by: CURRENT_USER, folder: 'Marketing/Website' }) },
        {
            ...dashboard({
                created_by: OTHER_USER,
                name: 'needle',
                folder: 'Marketing/Website',
            }),
        },
        {
            ...dashboard({
                created_by: CURRENT_USER,
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
            logic.actions.setFilters({ createdBy: [OTHER_USER.id] })
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

    it('filters client-side by folder when no search is active', async () => {
        const inFolder = allDashboards.filter((d) => (d as DashboardType).folder === 'Marketing/Website')
        expectLogic(logic, () => {
            logic.actions.setFilters({ folder: 'Marketing/Website' })
        }).toMatchValues({
            dashboards: truth(
                (dashboards: DashboardType[]) =>
                    dashboards.length === inFolder.length && dashboards.every((d) => d.folder === 'Marketing/Website')
            ),
        })
    })

    it('shows dashboards from all selected creators when multiple are chosen', async () => {
        // Multi-select is a union: selecting both users returns every dashboard, since each was
        // created by one of them.
        expectLogic(logic, () => {
            logic.actions.setFilters({ createdBy: [CURRENT_USER.id, OTHER_USER.id] })
        }).toMatchValues({
            dashboards: truth((dashboards: DashboardType[]) => dashboards.length === allDashboards.length),
        })
    })

    it('shows correct dashboards when filtering by name and shared', async () => {
        expectLogic(logic, () => {
            logic.actions.setFilters({ createdBy: [OTHER_USER.id], shared: true })
        }).toMatchValues({
            dashboards: [],
        })
    })

    it('shows correct dashboards when filtering by name and on pinned tab', async () => {
        expectLogic(logic, () => {
            logic.actions.setCurrentTab(DashboardsTab.Pinned)
            logic.actions.setFilters({ createdBy: [OTHER_USER.id] })
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
                '/api/environments/:team_id/dashboards/': ({ request }) => {
                    if (new URL(request.url).searchParams.get('search')) {
                        return [200, { count: 1, next: null, previous: null, results: [needleDashboard] }]
                    }
                    return [200, { count: 7, next: null, previous: null, results: allDashboards }]
                },
            },
        })

        const reportSearched = jest.spyOn(eventUsageLogic.actions, 'reportDashboardListSearched')
        await expectLogic(logic, () => {
            logic.actions.setSearch('needl')
        }).toDispatchActions(['loadSearchedDashboardsSuccess'])

        expect(logic.values.dashboards).toHaveLength(1)
        expect(logic.values.dashboards[0].name).toBe('needle')
        // Findability signal fires once per settled search: term length + result count, never the query text.
        // Covers the dashboards-list-view experiment instrumentation (flag: dashboards-list-view · experiment 379125).
        expect(reportSearched).toHaveBeenCalledWith(5, 1)
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
            logic.actions.setFilters({ createdBy: [999] })
        }).toNotHaveDispatchedActions(['loadSearchedDashboards'])
    })

    it('sends tag filters to the server alongside search', async () => {
        // Server-side tag filtering keeps MCP/API clients in sync with the UI and ensures
        // the limit:200 cap operates on the right population (pre-tag-filtered, not post).
        let lastRequestUrl: URL | null = null
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': ({ request }) => {
                    lastRequestUrl = new URL(request.url)
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

    const urlWriteCases: Array<{
        name: string
        set: Partial<DashboardsFilters>
        reset: Partial<DashboardsFilters>
        param: string
        expected: unknown
    }> = [
        {
            name: 'created_by',
            set: { createdBy: [2] },
            reset: { createdBy: 'All users' },
            param: 'created_by',
            expected: [2],
        },
        { name: 'pinned', set: { pinned: true }, reset: { pinned: false }, param: 'pinned', expected: true },
        { name: 'shared', set: { shared: true }, reset: { shared: false }, param: 'shared', expected: true },
        { name: 'tags', set: { tags: ['finance'] }, reset: { tags: [] }, param: 'tags', expected: ['finance'] },
    ]

    it.each(urlWriteCases)(
        'syncs $name to the URL and removes it on reset',
        async ({ set, reset, param, expected }) => {
            await expectLogic(logic, () => {
                logic.actions.setFilters(set)
            })
            expect(router.values.searchParams[param]).toEqual(expected)

            await expectLogic(logic, () => {
                logic.actions.setFilters(reset)
            })
            expect(router.values.searchParams[param]).toBeUndefined()
        }
    )

    const urlReadCases: Array<{
        name: string
        params: Record<string, unknown>
        expected: Partial<DashboardsFilters>
    }> = [
        { name: 'created_by', params: { created_by: [2] }, expected: { createdBy: [2] } },
        { name: 'pinned', params: { pinned: true }, expected: { pinned: true } },
        { name: 'shared', params: { shared: true }, expected: { shared: true } },
        { name: 'tags', params: { tags: ['finance', 'q4'] }, expected: { tags: ['finance', 'q4'] } },
    ]

    it.each(urlReadCases)('loads $name from the URL into filters on mount', async ({ params, expected }) => {
        logic.unmount()
        router.actions.push(urls.dashboards(), params)
        logic = dashboardsLogic({ tabId: '1' })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            filters: expect.objectContaining(expected),
        })
    })

    it('restores both search and tags from the URL and fetches with the restored tags', async () => {
        let lastRequestUrl: URL | null = null
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': ({ request }) => {
                    lastRequestUrl = new URL(request.url)
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
            },
        })

        logic.unmount()
        router.actions.push(urls.dashboards(), { search: 'sales', tags: ['finance'] })
        logic = dashboardsLogic({ tabId: '1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSearchedDashboardsSuccess'])

        expect(logic.values.filters).toEqual(expect.objectContaining({ search: 'sales', tags: ['finance'] }))
        expect(lastRequestUrl).not.toBeNull()
        expect(lastRequestUrl!.searchParams.get('search')).toBe('sales')
        expect(lastRequestUrl!.searchParams.getAll('tags')).toEqual(['finance'])
    })

    it('does not refetch when toggling pinned while a search is active on the /dashboard URL', async () => {
        // Toggling pinned writes ?pinned=true to the URL, which round-trips back through
        // urlToAction. The guard there must not re-dispatch setSearch and trigger a redundant
        // server search. (The earlier regression test runs on pathname '/' so it never matches
        // urlToAction — this one mounts on /dashboard to exercise that round trip.)
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': () => {
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
            },
        })

        logic.unmount()
        router.actions.push(urls.dashboards())
        logic = dashboardsLogic({ tabId: '1' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setSearch('sales')
        }).toDispatchActions(['loadSearchedDashboardsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setFilters({ pinned: true })
        }).toNotHaveDispatchedActions(['loadSearchedDashboards'])
    })
})
