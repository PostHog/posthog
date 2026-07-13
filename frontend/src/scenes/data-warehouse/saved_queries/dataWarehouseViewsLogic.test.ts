import { expectLogic } from 'kea-test-utils'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'

describe('dataWarehouseViewsLogic', () => {
    let logic: ReturnType<typeof dataWarehouseViewsLogic.build>
    let databaseLogic: ReturnType<typeof databaseTableListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/': { results: [] },
            },
            delete: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': [204],
            },
        })
        initKeaTests()
        databaseLogic = databaseTableListLogic()
        databaseLogic.mount()
        logic = dataWarehouseViewsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        databaseLogic.unmount()
    })

    // Regression: deleting a view used to leave the shared database schema stale, so the deleted
    // view kept showing up in dashboard/insight pickers. Deletion must trigger a schema refresh.
    it('refreshes the database schema after a saved query is deleted', async () => {
        await expectLogic(logic, () => {
            logic.actions.deleteDataWarehouseSavedQuery('view-123')
        }).toDispatchActions(['deleteDataWarehouseSavedQuerySuccess', 'refreshDatabaseSchema'])
    })
})
