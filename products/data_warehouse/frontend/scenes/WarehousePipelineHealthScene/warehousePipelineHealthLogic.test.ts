import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from 'products/data_warehouse/frontend/generated/api'
import type {
    ManagedWarehouseDataStatusResponseApi,
    ManagedWarehouseSourceTableStatusApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { managedWarehouseDataStatusLogic } from '../DataOpsScene/tabs/managedWarehouseDataStatusLogic'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseManagedWarehouseDataStatusRetrieve: jest.fn(),
    dataWarehouseManagedWarehouseSourceSchemasRetrieve: jest.fn(),
}))

const SOURCE_ID = '00000000-0000-0000-0000-000000000001'

const STATUS = {
    sources: { sources: [{ source_id: SOURCE_ID, source_type: 'Stripe', landing_state: 'behind' }] },
} as unknown as ManagedWarehouseDataStatusResponseApi

const SCHEMAS = [{ schema_id: 'schema-1', table_name: 'charges' }] as ManagedWarehouseSourceTableStatusApi[]

describe('warehousePipelineHealthLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(api.dataWarehouseManagedWarehouseDataStatusRetrieve).mockReset().mockResolvedValue(STATUS)
        jest.mocked(api.dataWarehouseManagedWarehouseSourceSchemasRetrieve)
            .mockReset()
            .mockResolvedValue({ schemas: SCHEMAS })
    })

    it('loads the tables of a source once, on the first time it opens', async () => {
        const logic = warehousePipelineHealthLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadManagedWarehouseDataStatusSuccess'])

        await expectLogic(logic, () => logic.actions.toggleSource(SOURCE_ID))
            .toDispatchActions(['loadSourceSchemasSuccess'])
            .toMatchValues({ expandedSourceSchemas: SCHEMAS })
        logic.actions.toggleSource(SOURCE_ID)
        await expectLogic(logic, () => logic.actions.toggleSource(SOURCE_ID)).toMatchValues({
            expandedSourceSchemas: SCHEMAS,
        })

        expect(api.dataWarehouseManagedWarehouseSourceSchemasRetrieve).toHaveBeenCalledTimes(1)
    })

    it('shows a failed tables load as failed, and a retry clears it', async () => {
        jest.mocked(api.dataWarehouseManagedWarehouseSourceSchemasRetrieve).mockRejectedValueOnce(new Error('nope'))
        const logic = warehousePipelineHealthLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadManagedWarehouseDataStatusSuccess'])

        await expectLogic(logic, () => logic.actions.toggleSource(SOURCE_ID))
            .toDispatchActions(['loadSourceSchemasFailure'])
            .toMatchValues({ schemasFailed: { [SOURCE_ID]: true }, expandedSourceSchemas: null })

        await expectLogic(logic, () => logic.actions.retrySourceSchemas(SOURCE_ID))
            .toDispatchActions(['loadSourceSchemasSuccess'])
            .toMatchValues({ schemasFailed: { [SOURCE_ID]: false }, expandedSourceSchemas: SCHEMAS })
    })

    it('reports a status load that failed, not one still loading', async () => {
        jest.mocked(api.dataWarehouseManagedWarehouseDataStatusRetrieve).mockRejectedValue(new Error('nope'))
        const logic = warehousePipelineHealthLogic()
        logic.mount()

        expect(logic.values.statusFailed).toBe(false)
        await expectLogic(managedWarehouseDataStatusLogic).toDispatchActions(['loadManagedWarehouseDataStatusFailure'])
        expect(logic.values.statusFailed).toBe(true)
    })
})
