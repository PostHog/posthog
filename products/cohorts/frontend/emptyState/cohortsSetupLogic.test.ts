import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { cohortsSetupLogic } from './cohortsSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('cohortsSetupLogic', () => {
    let listSpy: jest.SpyInstance

    beforeEach(() => {
        listSpy = jest.spyOn(generatedApi, 'cohortsList')
        initKeaTests()
    })

    afterEach(() => {
        listSpy.mockRestore()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [17, 'has-data'],
    ])('pushes a cohort count of %i as status %s', async (count, expected) => {
        listSpy.mockResolvedValue({ count, results: [] })
        const logic = cohortsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.COHORTS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        listSpy.mockRejectedValue(new Error('network down'))
        const logic = cohortsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.COHORTS }).values.status).toBe('unknown')
    })
})
