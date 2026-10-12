import { parseSelect } from './hogqlParserSingleton'
import { SELECTION_NOT_A_QUERY, findSelectionProblem } from './saveCandidateProblems'
import { SELECTION_LABEL, SaveCandidates } from './SaveTargetCycler'

jest.mock('./hogqlParserSingleton', () => {
    const actual = jest.requireActual('./hogqlParserSingleton')
    return { ...actual, parseSelect: jest.fn(actual.parseSelect) }
})

const candidates = (queries: string[], selectionLabel: string | null = null): SaveCandidates => ({
    queries,
    initialIndex: 0,
    selectionLabel,
})

describe('findSelectionProblem', () => {
    it('flags a highlighted identifier and points at the selection', async () => {
        const problem = await findSelectionProblem(candidates(['weekly_active_users'], SELECTION_LABEL), false)
        expect(problem).toEqual(SELECTION_NOT_A_QUERY)
    })

    it('accepts a selection that is a whole query', async () => {
        const problem = await findSelectionProblem(candidates(['SELECT 1'], SELECTION_LABEL), false)
        expect(problem).toBeNull()
    })

    it('leaves the editor contents to the API when nothing is selected', async () => {
        const problem = await findSelectionProblem(candidates(['weekly_active_users']), false)
        expect(problem).toBeNull()
    })

    it('leaves a raw connection selection alone, because it is not HogQL', async () => {
        const problem = await findSelectionProblem(
            candidates(['SELECT DISTINCT ON (id) id FROM t'], SELECTION_LABEL),
            true
        )
        expect(problem).toBeNull()
    })

    it('reports no problem when the parser cannot be loaded', async () => {
        ;(parseSelect as jest.Mock).mockRejectedValueOnce(new Error('parser unavailable'))
        const problem = await findSelectionProblem(candidates(['weekly_active_users'], SELECTION_LABEL), false)
        expect(problem).toBeNull()
    })
})
