import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    llmAnalyticsParserRecipesCreate,
    llmAnalyticsParserRecipesDestroy,
    llmAnalyticsParserRecipesList,
} from '../generated/api'
import { parserRecipesLogic } from './parserRecipesLogic'

jest.mock('../generated/api', () => ({
    llmAnalyticsParserRecipesList: jest.fn(),
    llmAnalyticsParserRecipesCreate: jest.fn(),
    llmAnalyticsParserRecipesPartialUpdate: jest.fn(),
    llmAnalyticsParserRecipesDestroy: jest.fn(),
}))

const mockList = llmAnalyticsParserRecipesList as jest.MockedFunction<typeof llmAnalyticsParserRecipesList>
const mockCreate = llmAnalyticsParserRecipesCreate as jest.MockedFunction<typeof llmAnalyticsParserRecipesCreate>
const mockDestroy = llmAnalyticsParserRecipesDestroy as jest.MockedFunction<typeof llmAnalyticsParserRecipesDestroy>

describe('parserRecipesLogic', () => {
    let logic: ReturnType<typeof parserRecipesLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        mockList.mockResolvedValue({ results: [] } as any)
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('fetches recipes on mount and maps them for the list and the merge', async () => {
        mockList.mockResolvedValue({ results: [{ id: 'r1', name: 'First', source: 'rules: []\n' }] } as any)
        logic = parserRecipesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecipesSuccess'])
        expect(mockList).toHaveBeenCalled()
        expect(logic.values.customItems).toEqual([{ id: 'r1', name: 'First', source: 'rules: []\n' }])
        expect(logic.values.storedForMerge).toEqual([{ id: 'r1', source: 'rules: []\n' }])
    })

    it('bumps recipesVersion every time loaded recipes are applied to the normalizer', async () => {
        logic = parserRecipesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecipesSuccess', 'recipesApplied'])
        expect(logic.values.recipesVersion).toBe(1)

        logic.actions.loadRecipes()
        await expectLogic(logic).toDispatchActions(['loadRecipesSuccess', 'recipesApplied'])
        expect(logic.values.recipesVersion).toBe(2)
    })

    it('surfaces a compile error for invalid editor source and clears it on close', () => {
        logic = parserRecipesLogic()
        logic.mount()
        logic.actions.openEditorForNew()
        expect(logic.values.editorCompileError).toBeNull()
        logic.actions.setEditorSource('not: [valid')
        expect(logic.values.editorCompileError).not.toBeNull()
        logic.actions.closeEditor()
        expect(logic.values.editor).toBeNull()
        expect(logic.values.editorCompileError).toBeNull()
    })

    it('rejects submit with an empty name and makes no request', async () => {
        logic = parserRecipesLogic()
        logic.mount()
        logic.actions.openEditorForNew()
        await expectLogic(logic, () => logic.actions.submitEditor()).toFinishAllListeners()
        expect(mockCreate).not.toHaveBeenCalled()
        expect(logic.values.savingEditor).toBe(false)
    })

    it('creates a recipe and closes the editor on submit', async () => {
        mockCreate.mockResolvedValue({ id: 'new' } as any)
        logic = parserRecipesLogic()
        logic.mount()
        logic.actions.openEditorForNew()
        logic.actions.setEditorName('My recipe')
        logic.actions.setEditorSource('rules: []\n')
        await expectLogic(logic, () => logic.actions.submitEditor()).toFinishAllListeners()
        expect(mockCreate).toHaveBeenCalledWith(expect.any(String), { name: 'My recipe', source: 'rules: []\n' })
        expect(logic.values.editor).toBeNull()
    })

    it('deletes a recipe', async () => {
        mockDestroy.mockResolvedValue(undefined as any)
        logic = parserRecipesLogic()
        logic.mount()
        await expectLogic(logic, () =>
            logic.actions.deleteItem({ id: 'r1', name: 'X', source: 'rules: []\n' })
        ).toFinishAllListeners()
        expect(mockDestroy).toHaveBeenCalledWith(expect.any(String), 'r1')
    })
})
