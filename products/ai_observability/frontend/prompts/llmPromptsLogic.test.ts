import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmPromptsList, llmPromptsNameUnarchiveCreate } from '../generated/api'
import { llmPromptsLogic } from './llmPromptsLogic'

jest.mock('../generated/api', () => ({
    llmPromptsList: jest.fn(),
    llmPromptsNameArchiveCreate: jest.fn(),
    llmPromptsNameUnarchiveCreate: jest.fn(),
}))

const mockList = llmPromptsList as jest.MockedFunction<typeof llmPromptsList>
const mockUnarchive = llmPromptsNameUnarchiveCreate as jest.MockedFunction<typeof llmPromptsNameUnarchiveCreate>

describe('llmPromptsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockList.mockResolvedValue({ results: [], count: 0 } as any)
    })

    it('passes the archived filter from a URL string to the list request', async () => {
        const logic = llmPromptsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // URL search params arrive as strings, not booleans.
        logic.actions.setFilters({ archived: 'true' as any }, true, false)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ archived: true }))

        logic.unmount()
    })

    it('restores a prompt, reloads the list, and clears the in-flight marker', async () => {
        mockUnarchive.mockResolvedValue({} as any)
        const logic = llmPromptsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockClear()

        logic.actions.restorePrompt('restored-prompt')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockUnarchive).toHaveBeenCalledWith(expect.any(String), 'restored-prompt')
        expect(mockList).toHaveBeenCalledTimes(1)
        expect(logic.values.restoringPromptName).toBeNull()

        logic.unmount()
    })
})
