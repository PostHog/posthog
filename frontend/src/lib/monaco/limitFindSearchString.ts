import type { IDisposable, editor as importedEditor } from 'monaco-editor'

// Monaco seeds the find input from the selection and escapes it into a regex, and only refuses
// to seed above 512 KiB. V8 gives up long before that ("regular expression too large") and the
// SyntaxError escapes the find model as an unhandled error. The cap sits far above any real
// search term, so find keeps working on the long single-line queries the SQL editor loads.
export const MAX_FIND_SEARCH_STRING_LENGTH = 1000

interface FindReplaceStateLike {
    change(newState: { searchString?: string }, moveCursor: boolean, updateHistory?: boolean): void
}

interface FindControllerLike extends importedEditor.IEditorContribution {
    getState(): FindReplaceStateLike
}

export function limitFindSearchString(codeEditor: importedEditor.IStandaloneCodeEditor): IDisposable {
    const findController = codeEditor.getContribution<FindControllerLike>('editor.contrib.findController')
    const state = typeof findController?.getState === 'function' ? findController.getState() : null
    if (!state || typeof state.change !== 'function') {
        // Internal contribution shape changed: degrade to the unbounded Monaco behavior
        return { dispose: () => {} }
    }
    const originalChange = state.change.bind(state)
    // Truncate inside `change` rather than from a state listener. Monaco's find model listens
    // first, so a listener only runs after the oversized search has already thrown.
    state.change = (newState, moveCursor, updateHistory): void => {
        const searchString = newState.searchString
        if (typeof searchString === 'string' && searchString.length > MAX_FIND_SEARCH_STRING_LENGTH) {
            newState = { ...newState, searchString: searchString.slice(0, MAX_FIND_SEARCH_STRING_LENGTH) }
        }
        originalChange(newState, moveCursor, updateHistory)
    }
    return {
        dispose: () => {
            state.change = originalChange
        },
    }
}
