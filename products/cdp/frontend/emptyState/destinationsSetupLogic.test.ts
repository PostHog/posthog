import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { destinationsSetupLogic } from './destinationsSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('destinationsSetupLogic', () => {
    let hogFunctionsSpy: jest.SpyInstance
    let pluginsSpy: jest.SpyInstance
    let batchExportsSpy: jest.SpyInstance

    beforeEach(() => {
        hogFunctionsSpy = jest.spyOn(generatedApi, 'hogFunctionsList')
        pluginsSpy = jest.spyOn(api, 'get')
        batchExportsSpy = jest.spyOn(api.batchExports, 'list')
        initKeaTests()
    })

    afterEach(() => {
        hogFunctionsSpy.mockRestore()
        pluginsSpy.mockRestore()
        batchExportsSpy.mockRestore()
    })

    // The scene lists hog functions, legacy plugin destinations, and batch exports together,
    // so the count is the sum of all three sources.
    it.each([
        [0, 0, 0, 'needs-setup'],
        [1, 0, 0, 'has-data'],
        [0, 2, 0, 'has-data'],
        [0, 0, 1, 'has-data'],
    ])(
        'pushes %i hog functions, %i plugin destinations, and %i batch exports as status %s',
        async (hogFunctions, plugins, batchExports, expected) => {
            hogFunctionsSpy.mockResolvedValue({ count: hogFunctions, next: null, previous: null, results: [] })
            pluginsSpy.mockResolvedValue({ count: plugins, results: [] })
            batchExportsSpy.mockResolvedValue({ count: batchExports, results: [] })
            const logic = destinationsSetupLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.PIPELINE_DESTINATIONS }).values.status).toBe(
                expected
            )
        }
    )

    it('fails open to unknown when a count query fails before any answer', async () => {
        hogFunctionsSpy.mockRejectedValue(new Error('network down'))
        pluginsSpy.mockResolvedValue({ count: 0, results: [] })
        batchExportsSpy.mockResolvedValue({ count: 0, results: [] })
        const logic = destinationsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.PIPELINE_DESTINATIONS }).values.status).toBe('unknown')
    })
})
