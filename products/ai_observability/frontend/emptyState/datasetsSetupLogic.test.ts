import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { datasetsSetupLogic } from './datasetsSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('datasetsSetupLogic', () => {
    let listSpy: jest.SpyInstance

    beforeEach(() => {
        listSpy = jest.spyOn(generatedApi, 'datasetsList')
        initKeaTests()
    })

    afterEach(() => {
        listSpy.mockRestore()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [12, 'has-data'],
    ])('pushes a dataset count of %i as status %s', async (count, expected) => {
        listSpy.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = datasetsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LLM_DATASETS }).values.status).toBe(expected)
    })
})
