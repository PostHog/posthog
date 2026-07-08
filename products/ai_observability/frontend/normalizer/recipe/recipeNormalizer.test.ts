import { AVAILABLE_TOOLS_ROLE } from '../../utils'
import { RecipeNormalizer } from './recipeNormalizer'

const mockRun = jest.fn()

jest.mock('./registry', () => ({ loadRecipes: () => [] }))
jest.mock('./runtime/pipeline', () => ({
    RecipePipeline: jest.fn().mockImplementation(() => ({ run: mockRun })),
}))

describe('RecipeNormalizer', () => {
    let normalizer: RecipeNormalizer

    beforeEach(() => {
        jest.clearAllMocks()
        normalizer = new RecipeNormalizer()
    })

    describe('normalizeMessage', () => {
        it("returns the pipeline's outcome for a matched input", () => {
            const outcome = { messages: [{ role: 'assistant', content: 'hi' }], recognized: true }
            mockRun.mockReturnValue(outcome)
            expect(normalizer.normalizeMessage({ role: 'assistant' }, 'user')).toBe(outcome)
        })

        it('returns an empty recognized result for undefined input without dispatching', () => {
            expect(normalizer.normalizeMessage(undefined, 'user')).toEqual({ messages: [], recognized: true })
            expect(mockRun).not.toHaveBeenCalled()
        })

        it('passes through an unrecognized outcome without throwing', () => {
            mockRun.mockReturnValue({ messages: [{ role: 'user', content: 'salvaged' }], recognized: false })
            expect(normalizer.normalizeMessage({ weird: true }, 'user')).toEqual({
                messages: [{ role: 'user', content: 'salvaged' }],
                recognized: false,
            })
        })
    })

    describe('normalizeMessages', () => {
        it('prepends an available-tools message when tools are given', () => {
            mockRun.mockReturnValue({ messages: [{ role: 'assistant', content: 'hi' }], recognized: true })
            const tools = [{ name: 'search' }]
            expect(normalizer.normalizeMessages({ role: 'assistant' }, 'user', tools)).toEqual({
                messages: [
                    { role: AVAILABLE_TOOLS_ROLE, content: '', tools },
                    { role: 'assistant', content: 'hi' },
                ],
                recognized: true,
            })
        })

        it('propagates the recognized verdict from the input dispatch', () => {
            mockRun.mockReturnValue({ messages: [{ role: 'assistant', content: 'hi' }], recognized: false })
            expect(normalizer.normalizeMessages({ role: 'assistant' }, 'user')).toEqual({
                messages: [{ role: 'assistant', content: 'hi' }],
                recognized: false,
            })
        })
    })
})
