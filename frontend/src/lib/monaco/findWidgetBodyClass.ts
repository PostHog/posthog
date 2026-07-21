import { IDisposable, editor as importedEditor } from 'monaco-editor'

// Mirrors the find widget's visibility onto <body> so CodeEditorImpl.scss can style Monaco's
// body-level hover tooltips without a `body:has()` anchor. Near-root `:has()` selectors make
// Blink flag the whole document as :has-invalidation-suspect at load, after which any class
// change anywhere costs a full-document style recalc (see the same pattern in Notebook.scss).
const FIND_WIDGET_OPEN_BODY_CLASS = 'has-monaco-find-widget-open'

// Counts editors with an open find widget, so the body class survives multiple editors
let openFindWidgetCount = 0

interface FindReplaceStateLike {
    readonly isRevealed: boolean
    onFindReplaceStateChange(listener: (event: { isRevealed: boolean }) => void): IDisposable
}

interface FindControllerLike extends importedEditor.IEditorContribution {
    getState(): FindReplaceStateLike
}

export function trackFindWidgetVisibility(codeEditor: importedEditor.IStandaloneCodeEditor): IDisposable {
    const findController = codeEditor.getContribution<FindControllerLike>('editor.contrib.findController')
    const state = typeof findController?.getState === 'function' ? findController.getState() : null
    if (!state || typeof state.onFindReplaceStateChange !== 'function') {
        // Internal contribution shape changed: degrade to the tooltip flicker workaround not applying
        return { dispose: () => {} }
    }
    let revealed = false
    const setRevealed = (nextRevealed: boolean): void => {
        if (nextRevealed === revealed) {
            return
        }
        revealed = nextRevealed
        openFindWidgetCount += revealed ? 1 : -1
        document.body.classList.toggle(FIND_WIDGET_OPEN_BODY_CLASS, openFindWidgetCount > 0)
    }
    setRevealed(state.isRevealed)
    const listener = state.onFindReplaceStateChange((event) => {
        // The event carries change flags per field, the current value lives on the state
        if (event.isRevealed) {
            setRevealed(state.isRevealed)
        }
    })
    return {
        dispose: () => {
            listener.dispose()
            setRevealed(false)
        },
    }
}
