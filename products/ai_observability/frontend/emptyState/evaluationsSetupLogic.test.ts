import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { evaluationsSetupLogic } from './evaluationsSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('evaluationsSetupLogic', () => {
    let evaluationsSpy: jest.SpyInstance
    let directoriesSpy: jest.SpyInstance

    beforeEach(() => {
        evaluationsSpy = jest.spyOn(generatedApi, 'evaluationsList')
        directoriesSpy = jest.spyOn(generatedApi, 'evaluationDirectoriesList')
        initKeaTests()
    })

    afterEach(() => {
        evaluationsSpy.mockRestore()
        directoriesSpy.mockRestore()
    })

    it.each([
        [0, 0, 'needs-setup'],
        [1, 0, 'has-data'],
        [0, 1, 'has-data'],
    ])('pushes %i evaluations and %i directories as status %s', async (evaluationCount, directoryCount, expected) => {
        evaluationsSpy.mockResolvedValue({ count: evaluationCount, next: null, previous: null, results: [] })
        directoriesSpy.mockResolvedValue(Array.from({ length: directoryCount }, (_, i) => ({ id: String(i) })))
        const logic = evaluationsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LLM_EVALUATIONS }).values.status).toBe(expected)
    })
})
