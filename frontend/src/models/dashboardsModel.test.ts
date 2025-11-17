import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardBasicType } from '~/types'

import { dashboardsModel, nameCompareFunction } from './dashboardsModel'

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
})
