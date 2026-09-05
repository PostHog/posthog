import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as warehouseSourcesApi from 'products/warehouse_sources/frontend/generated/api'

import { dataWarehouseSetupLogic } from './dataWarehouseSetupLogic'

describe('dataWarehouseSetupLogic', () => {
    it('checks source existence without loading source rows', async () => {
        initKeaTests()
        const sourcesSpy = jest
            .spyOn(warehouseSourcesApi, 'externalDataSourcesExistsRetrieve')
            .mockResolvedValue({ exists: true })
        jest.spyOn(api.dataWarehouseTables, 'list').mockResolvedValue({ results: [] })

        const logic = dataWarehouseSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(sourcesSpy).toHaveBeenCalledWith(expect.any(String))
        expect(productSetupStatusLogic({ productKey: ProductKey.DATA_WAREHOUSE }).values.status).toBe('has-data')
    })
})
