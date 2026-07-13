import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'

describe('dataWarehouseViewsLogic', () => {
    let logic: ReturnType<typeof dataWarehouseViewsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.dataWarehouseSavedQueries, 'list').mockResolvedValue({ results: [] } as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('falls back to no folders when the folders endpoint returns 403', async () => {
        // Access-restricted users hit an RBAC 403 on this endpoint; it must not surface as an error.
        jest.spyOn(api.dataWarehouseSavedQueryFolders, 'list').mockRejectedValue(new ApiError('Forbidden', 403))

        logic = dataWarehouseViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadDataWarehouseSavedQueryFoldersSuccess'])

        expect(logic.values.dataWarehouseSavedQueryFolders).toEqual([])
    })

    it('rethrows non-403 errors from the folders endpoint', async () => {
        jest.spyOn(api.dataWarehouseSavedQueryFolders, 'list').mockRejectedValue(new ApiError('Boom', 500))

        logic = dataWarehouseViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadDataWarehouseSavedQueryFoldersFailure'])
    })
})
