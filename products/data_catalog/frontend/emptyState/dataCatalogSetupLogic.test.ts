import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { metricsLogic } from '../metricsLogic'
import { dataCatalogSetupLogic } from './dataCatalogSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('dataCatalogSetupLogic', () => {
    let listSpy: jest.SpyInstance

    beforeEach(() => {
        listSpy = jest.spyOn(generatedApi, 'dataCatalogMetricsList')
        initKeaTests()
    })

    afterEach(() => {
        listSpy.mockRestore()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [9, 'has-data'],
    ])('pushes a metric count of %i as status %s', async (count, expected) => {
        listSpy.mockResolvedValue({ count, results: [] })
        const logic = dataCatalogSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.DATA_CATALOG }).values.status).toBe(expected)
    })

    it('re-detects when a metric is created without leaving the scene', async () => {
        let catalogSize = 0
        listSpy.mockImplementation(async () => ({ count: catalogSize, results: [] }))
        const logic = dataCatalogSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.DATA_CATALOG }).values.status).toBe('needs-setup')

        // The empty state's modal creates the metric in place, so without the recheck
        // wiring the gate would keep hiding it until the user re-entered the scene.
        catalogSize = 1
        metricsLogic.mount()
        metricsLogic.actions.loadMetricsSuccess([])
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.DATA_CATALOG }).values.status).toBe('has-data')
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        listSpy.mockRejectedValue(new Error('network down'))
        const logic = dataCatalogSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.DATA_CATALOG }).values.status).toBe('unknown')
    })
})
