import { expectLogic, truth } from 'kea-test-utils'

import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'
import { DashboardType, UserBasicType } from '~/types'

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
    ]

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/': {
                    count: 6,
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
                return dashboards.length === 4 && dashboards.every((d) => d.created_by?.uuid === 'USER_UUID')
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

    it('shows correct dashboards when searching', async () => {
        expectLogic(logic, () => {
            logic.actions.setFilters({ search: 'needl' })
        }).toMatchValues({
            dashboards: truth((dashboards: DashboardType[]) => {
                return dashboards.length === 1 && dashboards[0].name === 'needle'
            }),
        })
    })
})
