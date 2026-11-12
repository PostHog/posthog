import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { businessKnowledgeSetupLogic } from './businessKnowledgeSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('businessKnowledgeSetupLogic', () => {
    let listSpy: jest.SpyInstance
    let reposSpy: jest.SpyInstance

    beforeEach(() => {
        listSpy = jest.spyOn(generatedApi, 'businessKnowledgeSourcesList')
        reposSpy = jest.spyOn(generatedApi, 'businessKnowledgeRepositoriesStatusRetrieve')
        initKeaTests()
    })

    afterEach(() => {
        listSpy.mockRestore()
        reposSpy.mockRestore()
    })

    it.each([
        [0, [], 'needs-setup'],
        [1, [], 'has-data'],
        [9, [], 'has-data'],
        [0, ['example/docs'], 'has-data'],
        [0, null, 'unknown'],
    ])('pushes %i sources and repositories %j as status %s', async (count, repos, expected) => {
        listSpy.mockResolvedValue({ count, next: null, previous: null, results: [] })
        if (repos) {
            reposSpy.mockResolvedValue({
                connected: repos.length > 0,
                integration_id: repos.length > 0 ? 1 : null,
                integration_name: '',
                repos,
            })
        } else {
            reposSpy.mockRejectedValue(new Error('repository status failed'))
        }
        const logic = businessKnowledgeSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.BUSINESS_KNOWLEDGE }).values.status).toBe(expected)
    })
})
