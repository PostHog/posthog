import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { llmPromptsList } from 'products/ai_observability/frontend/generated/api'

import { llmPromptsSetupLogic } from './llmPromptsSetupLogic'

jest.mock('products/ai_observability/frontend/generated/api', () => ({
    llmPromptsList: jest.fn(),
}))

const mockLlmPromptsList = llmPromptsList as jest.MockedFunction<typeof llmPromptsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('llmPromptsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [42, 'has-data'],
    ])('pushes a prompt count of %i as status %s', async (count, expected) => {
        mockLlmPromptsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = llmPromptsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LLM_PROMPTS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockLlmPromptsList.mockRejectedValue(new Error('network down'))
        const logic = llmPromptsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LLM_PROMPTS }).values.status).toBe('unknown')
    })
})
