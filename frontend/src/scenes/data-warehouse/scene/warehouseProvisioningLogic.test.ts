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

    it('removes the org record once teardown reports the warehouse deleted', async () => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue({ state: 'deleted' } as any)
        const deleteOrg = jest.spyOn(dwApi, 'dataWarehouseDeleteOrgDestroy').mockResolvedValue({} as any)

        logic = warehouseProvisioningLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWarehouseStatusSuccess', 'deleteOrg'])
        expect(deleteOrg).toHaveBeenCalledTimes(1)
    })

    it('retries removing the org record when the first delete-org attempt fails', async () => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue({ state: 'deleted' } as any)
        const deleteOrg = jest
            .spyOn(dwApi, 'dataWarehouseDeleteOrgDestroy')
            .mockRejectedValueOnce({ message: 'boom' })
            .mockResolvedValue({} as any)

        logic = warehouseProvisioningLogic()
        logic.mount()

        // First attempt fails and settles, clearing the in-flight guard.
        await expectLogic(logic).toDispatchActions(['deleteOrg', 'deleteOrgComplete'])
        expect(logic.values.isDeletingOrg).toBe(false)

        // The next poll re-observing `deleted` re-fires delete-org rather than staying stuck.
        await expectLogic(logic, () => {
            logic.actions.loadWarehouseStatusSuccess({ state: 'deleted' } as any)
        }).toDispatchActions(['deleteOrg'])
        expect(deleteOrg).toHaveBeenCalledTimes(2)
    })

    it('flags a stuck teardown once it sits in `deleting` past the warn threshold', async () => {
        logic = warehouseProvisioningLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWarehouseStatusSuccess'])

        // One `deleting` read is still "in progress", not yet "taking long".
        await expectLogic(logic, () => {
            logic.actions.loadWarehouseStatusSuccess({ state: 'deleting' } as any)
        }).toMatchValues({ deprovisionTakingLong: false })

        // 18 consecutive `deleting` reads (~3 min of polling) trips the affordance.
        await expectLogic(logic, () => {
            for (let i = 0; i < 17; i++) {
                logic.actions.loadWarehouseStatusSuccess({ state: 'deleting' } as any)
            }
        }).toMatchValues({ deprovisionTakingLong: true })

        // A non-`deleting` read resets the counter.
        await expectLogic(logic, () => {
            logic.actions.loadWarehouseStatusSuccess({ state: 'ready' } as any)
        }).toMatchValues({ deprovisionTakingLong: false })
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
