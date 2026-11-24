import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { initKeaTests } from '~/test/init'

import * as api from '../../generated/api'
import type { WarehouseStatusResponseApi } from '../../generated/api.schemas'
import { warehouseShellStatusLogic } from './warehouseShellStatusLogic'

function status(state: string, trinoState: string): WarehouseStatusResponseApi {
    return {
        state,
        trino: { state: trinoState, hoglake: false, connection: null },
    } as unknown as WarehouseStatusResponseApi
}

describe('warehouseShellStatusLogic', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true })
    })

    afterEach(() => jest.restoreAllMocks())

    it.each([
        ['no warehouse', () => Promise.reject({ status: 404 }), 'loadWarehouseStatusSuccess', false],
        ['a failed load', () => Promise.reject(new Error('boom')), 'loadWarehouseStatusFailure', null],
        ['a ready warehouse', () => Promise.resolve(status('ready', 'ready')), 'loadWarehouseStatusSuccess', true],
        [
            'a warehouse still provisioning',
            () => Promise.resolve(status('provisioning', 'pending')),
            'loadWarehouseStatusSuccess',
            true,
        ],
    ])('reports %s to the shell', async (_name, response, settledAction, expected) => {
        jest.spyOn(api, 'dataWarehouseWarehouseStatusRetrieve').mockImplementation(response as never)
        todayShellLogic.mount()
        const logic = warehouseShellStatusLogic()
        logic.mount()
        expect(todayShellLogic.values.warehouseProvisioned).toBeNull()

        await expectLogic(logic).toDispatchActions([settledAction])
        expect(todayShellLogic.values.warehouseProvisioned).toBe(expected)
    })
})
