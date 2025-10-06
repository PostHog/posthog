import { initKeaTests } from '~/test/init'
import { DataWarehouseActivityRecord } from '~/types'

import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'

describe('dataWarehouseSceneLogic', () => {
    let logic: ReturnType<typeof dataWarehouseSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = dataWarehouseSceneLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('pagination functionality', () => {
        it('calculates pagination state correctly', () => {
            const mockActivity: DataWarehouseActivityRecord[] = Array.from({ length: 12 }, (_, i) => ({
                id: `activity-${i}`,
                name: `Activity ${i}`,
                type: 'test',
                status: 'completed',
                created_at: '2023-01-01T00:00:00Z',
                finished_at: '2023-01-01T00:00:00Z',
                latest_error: null,
                rows: 100,
            }))

            logic.mount()
            logic.actions.loadRecentActivityResponseSuccess({ results: mockActivity, next: null })

            expect(logic.values.activityPaginationState).toMatchObject({
                currentPage: 1,
                pageCount: 3, // 12 items / 5 per page = 2.4, rounded up to 3
                entryCount: 12,
                currentStartIndex: 0,
                currentEndIndex: 5,
                dataSourcePage: mockActivity.slice(0, 5),
                isOnLastPage: false,
                hasDataOnCurrentPage: true,
            })
        })

        it('updates current page correctly', () => {
            const mockActivity: DataWarehouseActivityRecord[] = Array.from({ length: 12 }, (_, i) => ({
                id: `activity-${i}`,
                name: `Activity ${i}`,
                type: 'test',
                status: 'completed',
                created_at: '2023-01-01T00:00:00Z',
                finished_at: '2023-01-01T00:00:00Z',
                latest_error: null,
                rows: 100,
            }))

            logic.mount()
            logic.actions.loadRecentActivityResponseSuccess({ results: mockActivity, next: null })
            logic.actions.setActivityCurrentPage(2)

            expect(logic.values.activityPaginationState).toMatchObject({
                currentPage: 2,
                currentStartIndex: 5,
                currentEndIndex: 10,
                dataSourcePage: mockActivity.slice(5, 10),
                isOnLastPage: false,
                hasDataOnCurrentPage: true,
            })
        })
    })
})
