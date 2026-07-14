import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as dwApi from 'products/data_warehouse/frontend/generated/api'
import type { ManagedWarehouseUserApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { dbUsersLogic } from './dbUsersLogic'
import { warehouseProvisioningLogic } from './warehouseProvisioningLogic'

describe('dbUsersLogic', () => {
    let logic: ReturnType<typeof dbUsersLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue({
            state: 'ready',
            connection: { host: 'warehouse.example.com', port: 5432, database: 'ducklake', username: 'root' },
        } as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('stashes the one-time password and refreshes the list after creating a user', async () => {
        jest.spyOn(dwApi, 'dataWarehouseUsersList')
            .mockResolvedValueOnce([])
            .mockResolvedValueOnce([
                { username: 'alice', disabled: false, created_at: '2026-01-01', updated_at: '2026-01-01' },
            ] as ManagedWarehouseUserApi[])
        jest.spyOn(dwApi, 'dataWarehouseUsersCreate').mockResolvedValue({
            username: 'alice',
            password: 'one-time-secret',
            connection: { host: 'warehouse.example.com', port: 5432, database: 'ducklake', username: 'alice' },
        })

        logic = dbUsersLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDbUsersSuccess'])

        await expectLogic(logic, () => {
            logic.actions.createUser('alice')
        }).toDispatchActions(['createUser', 'createUserComplete', 'loadDbUsersSuccess'])

        expect(logic.values.credentials).toEqual({
            action: 'create',
            username: 'alice',
            password: 'one-time-secret',
            connection: { host: 'warehouse.example.com', port: 5432, database: 'ducklake', username: 'alice' },
        })
        expect(logic.values.dbUsers.map((u) => u.username)).toEqual(['alice'])
        expect(dwApi.dataWarehouseUsersList).toHaveBeenCalledTimes(2)
    })

    it('clears the stashed credentials once the modal is closed', async () => {
        jest.spyOn(dwApi, 'dataWarehouseUsersList').mockResolvedValue([])
        jest.spyOn(dwApi, 'dataWarehouseUsersCreate').mockResolvedValue({
            username: 'bob',
            password: 'another-secret',
            connection: null,
        })

        logic = dbUsersLogic()
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.createUser('bob')
        }).toDispatchActions(['createUserComplete'])
        expect(logic.values.credentials).not.toBeNull()

        logic.actions.clearCredentials()
        expect(logic.values.credentials).toBeNull()
    })

    it("builds reset-password connection details from the warehouse's own connection info", async () => {
        jest.spyOn(dwApi, 'dataWarehouseUsersList').mockResolvedValue([])
        jest.spyOn(dwApi, 'dataWarehouseUsersResetPasswordCreate').mockResolvedValue({
            username: 'alice',
            password: 'new-secret',
        })

        logic = dbUsersLogic()
        logic.mount()
        // Wait for warehouseProvisioningLogic's connected `warehouseStatus` to resolve, since
        // resetPassword's connection details are derived from it. dbUsersLogic only connects to
        // its *values*, not its actions, so the wait has to target the owning logic directly.
        await expectLogic(warehouseProvisioningLogic).toDispatchActions(['loadWarehouseStatusSuccess'])

        await expectLogic(logic, () => {
            logic.actions.resetPassword('alice')
        }).toDispatchActions(['resetPasswordComplete'])

        expect(logic.values.credentials).toEqual({
            action: 'reset',
            username: 'alice',
            password: 'new-secret',
            connection: { host: 'warehouse.example.com', port: 5432, database: 'ducklake', username: 'alice' },
        })
    })
})
