import { parseSelect } from './hogqlParserSingleton'
import { SELECTION_LABEL, SaveCandidates } from './SaveTargetCycler'

export const SELECTION_NOT_A_QUERY =
    'The selected text is not a complete query. Clear the selection to save the whole query.'

/**
 * Report why the chosen save candidate cannot be saved, or null when it is fine.
 *
 * Only a selection is judged. It is the one candidate a person does not mean to choose: a
 * double-click leaves a single identifier highlighted, and that then wins over the whole editor
 * contents. Clearing the selection is always a way forward, so a wrong verdict here cannot trap
 * anyone. The whole editor contents are left to the API, whose parser is the one that decides.
 *
 * Fails open. When the parser is unavailable we cannot tell a broken query from an unchecked one.
 */
export async function findSelectionProblem(candidates: SaveCandidates): Promise<string | null> {
    if (candidates.selectionLabel !== SELECTION_LABEL) {
        return null
    }
    const selected = candidates.queries[candidates.initialIndex] ?? ''
    return (await isParsable(selected)) ? null : SELECTION_NOT_A_QUERY
}

async function isParsable(query: string): Promise<boolean> {
    try {
        // parseSelect reports a syntax error inside its result rather than rejecting, so a
        // rejection here means the parser itself failed to load.
        const parsed = JSON.parse(await parseSelect(query))
        return parsed?.error !== true
    } catch {
        return true
    }
}
