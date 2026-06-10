import { AVAILABLE_TOOLS_ROLE } from '../../utils'
import { RecipeNormalizer } from './recipeNormalizer'
import { NO_MATCH } from './runtime/pipeline'

const mockRun = jest.fn()

jest.mock('./registry', () => ({ loadRecipes: () => [] }))
jest.mock('./runtime/pipeline', () => ({
    NO_MATCH: Symbol('no-match'),
    RecipePipeline: jest.fn().mockImplementation(() => ({ run: mockRun })),
}))

describe('RecipeNormalizer', () => {
    let normalizer: RecipeNormalizer

    beforeEach(() => {
        jest.clearAllMocks()
        normalizer = new RecipeNormalizer()
    })

    describe('normalizeMessage', () => {
        it("returns the pipeline's normalized messages for a matched input", () => {
            const messages = [{ role: 'assistant', content: 'hi' }]
            mockRun.mockReturnValue(messages)
            expect(normalizer.normalizeMessage({ role: 'assistant' }, 'user')).toBe(messages)
        })

        it('returns no messages for undefined input without dispatching', () => {
            expect(normalizer.normalizeMessage(undefined, 'user')).toEqual([])
            expect(mockRun).not.toHaveBeenCalled()
        })

        it('throws when nothing matches (catch-all coverage gap)', () => {
            mockRun.mockReturnValue(NO_MATCH)
            expect(() => normalizer.normalizeMessage({ weird: true }, 'user')).toThrow(/no recipe matched/)
        })
    })

    describe('normalizeMessages', () => {
        it('prepends an available-tools message when tools are given', () => {
            mockRun.mockReturnValue([{ role: 'assistant', content: 'hi' }])
            const tools = [{ name: 'search' }]
            expect(normalizer.normalizeMessages({ role: 'assistant' }, 'user', tools)).toEqual([
                { role: AVAILABLE_TOOLS_ROLE, content: '', tools },
                { role: 'assistant', content: 'hi' },
            ])
        })

        it('without tools just returns the normalized messages', () => {
            const messages = [{ role: 'assistant', content: 'hi' }]
            mockRun.mockReturnValue(messages)
            expect(normalizer.normalizeMessages({ role: 'assistant' }, 'user')).toEqual(messages)
        })
    })
})
