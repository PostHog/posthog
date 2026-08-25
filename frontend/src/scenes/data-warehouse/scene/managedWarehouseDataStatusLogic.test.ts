import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { dataWarehouseManagedWarehouseDataStatusRetrieve } from 'products/data_warehouse/frontend/generated/api'

import { managedWarehouseDataStatusLogic } from './managedWarehouseDataStatusLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseManagedWarehouseDataStatusRetrieve: jest.fn(),
}))

const mockRetrieve = dataWarehouseManagedWarehouseDataStatusRetrieve as jest.Mock

describe('managedWarehouseDataStatusLogic', () => {
    let logic: ReturnType<typeof managedWarehouseDataStatusLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockRetrieve.mockReset()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('flags a failed load as an error, not an empty warehouse', async () => {
        mockRetrieve.mockRejectedValueOnce({ status: 500 })
        logic = managedWarehouseDataStatusLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadManagedWarehouseDataStatusFailure'])
        expect(logic.values.loadError).toBe(true)
        expect(logic.values.managedWarehouseDataStatus).toBeNull()
    })

    it('clears the error once a load succeeds', async () => {
        mockRetrieve.mockRejectedValueOnce({ status: 500 })
        logic = managedWarehouseDataStatusLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadManagedWarehouseDataStatusFailure'])

        mockRetrieve.mockResolvedValueOnce({ overall_readiness_state: 'up_to_date' })
        logic.actions.loadManagedWarehouseDataStatus()

        await expectLogic(logic).toDispatchActions(['loadManagedWarehouseDataStatusSuccess'])
        expect(logic.values.loadError).toBe(false)
    })
})
