import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import * as dwApi from 'products/data_warehouse/frontend/generated/api'

import { warehouseProvisioningLogic } from './warehouseProvisioningLogic'

describe('warehouseProvisioningLogic', () => {
    let logic: ReturnType<typeof warehouseProvisioningLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue(null as any)
        jest.spyOn(dwApi, 'dataWarehouseCheckDatabaseNameRetrieve').mockResolvedValue({
            name: '',
            available: true,
        } as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads warehouse status on mount', async () => {
        logic = warehouseProvisioningLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWarehouseStatus', 'loadWarehouseStatusSuccess'])
        expect(dwApi.dataWarehouseWarehouseStatusRetrieve).toHaveBeenCalled()
    })

    it('treats a 404 status as no warehouse', async () => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockRejectedValueOnce({ status: 404 })

        logic = warehouseProvisioningLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWarehouseStatusSuccess'])
        expect(logic.values.warehouseStatus).toBeNull()
    })

    it('validates database names and gates provisioning on availability', async () => {
        logic = warehouseProvisioningLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setDatabaseName('Bad Name')
        }).toMatchValues({ isValidDatabaseName: false, canProvision: false })

        // Underscores are not valid in a DNS subdomain
        await expectLogic(logic, () => {
            logic.actions.setDatabaseName('bad_name')
        }).toMatchValues({ isValidDatabaseName: false })

        await expectLogic(logic, () => {
            logic.actions.setDatabaseName('valid-name')
            logic.actions.setDatabaseNameAvailable(true)
        }).toMatchValues({ isValidDatabaseName: true, canProvision: true })
    })

    it('surfaces an info message instead of an error when a sibling project already provisioned (409)', async () => {
        jest.spyOn(dwApi, 'dataWarehouseProvisionCreate').mockRejectedValueOnce({ status: 409 })
        const infoToast = jest.spyOn(lemonToast, 'info').mockReturnValue(undefined as any)
        const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)

        logic = warehouseProvisioningLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.provisionWarehouse({ databaseName: 'shared-warehouse', tableName: 'shared' })
        }).toDispatchActions(['provisionWarehouse', 'loadWarehouseStatus', 'provisionWarehouseComplete'])

        expect(infoToast).toHaveBeenCalledTimes(1)
        expect(errorToast).not.toHaveBeenCalled()
    })
})
