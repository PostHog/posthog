import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as api from '../../generated/api'
import type { WarehouseStatusResponseApi } from '../../generated/api.schemas'
import { warehouseProvisioningLogic } from '../DataOpsScene/tabs/warehouseProvisioningLogic'
import { warehouseConsoleLogic } from './warehouseConsoleLogic'

function status(state: string, trinoState: string): WarehouseStatusResponseApi {
    return {
        state,
        trino: { state: trinoState, hoglake: false, connection: null },
    } as unknown as WarehouseStatusResponseApi
}

describe('warehouseConsoleLogic', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true })
    })

    afterEach(() => jest.restoreAllMocks())

    it('is ready when it mounts after the status already loaded', async () => {
        jest.spyOn(api, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue(status('ready', 'ready'))
        const provisioning = warehouseProvisioningLogic()
        provisioning.mount()
        await expectLogic(provisioning).toDispatchActions(['loadWarehouseStatusSuccess'])

        const logic = warehouseConsoleLogic()
        logic.mount()

        expect(logic.values.consoleState).toBe('ready')
    })

    it.each([
        ['no warehouse', () => Promise.reject({ status: 404 }), 'no_warehouse'],
        ['a failed load', () => Promise.reject(new Error('boom')), 'error'],
        ['a warehouse still provisioning', () => Promise.resolve(status('provisioning', 'pending')), 'not_ready'],
        ['trino not ready', () => Promise.resolve(status('ready', 'provisioning')), 'not_ready'],
    ])('reports %s', async (_name, response, expected) => {
        jest.spyOn(api, 'dataWarehouseWarehouseStatusRetrieve').mockImplementation(response as never)
        const logic = warehouseConsoleLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions([
            expected === 'error' ? 'loadWarehouseStatusFailure' : 'loadWarehouseStatusSuccess',
        ])
        expect(logic.values.consoleState).toBe(expected)
    })
})
