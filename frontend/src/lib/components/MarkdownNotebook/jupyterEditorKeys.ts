import type { IDisposable, IPosition, editor, languages } from 'monaco-editor'

import type { MountedCodeEditor } from 'lib/monaco/mountedCodeEditors'
import { isMac } from 'lib/utils/dom'

export type NotebookJupyterCompletions = {
    matches: { text: string; type: string }[]
    cursorStart: number
    cursorEnd: number
}

export type NotebookJupyterEditorKeyHandlers = {
    onSplit: (offset: number) => void
    onLeaveCell: (direction: 'previous' | 'next') => void
    onDeleteEmptyCell: () => void
    /** Completions from the kernel for the cursor position; without it Tab uses the editor's own suggestions. */
    complete?: (code: string, cursorPos: number) => Promise<NotebookJupyterCompletions | null>
    /** The signature and docstring of the name at the cursor; without it Shift+Tab only outdents. */
    inspect?: (code: string, cursorPos: number) => Promise<string | null>
}

const CODE_BEFORE_CURSOR = /[\w.)\]('"]$/
// The arrow keys keep their usual job wherever a list, a selection, or a second cursor is in play.
const EDGE_KEY_PRECONDITION =
    'editorTextFocus && !suggestWidgetVisible && !parameterHintsVisible && !editorHasSelection && !editorHasMultipleSelections'

function completionKind(monaco: MountedCodeEditor['monaco'], type: string): languages.CompletionItemKind {
    const kinds = monaco.languages.CompletionItemKind
    const byType: Record<string, languages.CompletionItemKind> = {
        function: kinds.Function,
        builtin_function_or_method: kinds.Function,
        method: kinds.Method,
        class: kinds.Class,
        type: kinds.Class,
        module: kinds.Module,
        keyword: kinds.Keyword,
        instance: kinds.Variable,
        statement: kinds.Variable,
        param: kinds.Variable,
        path: kinds.File,
        magic: kinds.Snippet,
    }
    return byType[type] ?? kinds.Text
}

function textBeforeCursor(model: editor.ITextModel, position: IPosition): string {
    return model.getLineContent(position.lineNumber).slice(0, position.column - 1)
}

/**
 * Jupyter's edit-mode keys on one cell's code editor: Tab completes after code and indents
 * elsewhere, Shift+Tab shows the docs for the name at the cursor, Ctrl+Shift+Minus splits the cell.
 * Returns the cleanup.
 */
export function installNotebookJupyterEditorKeys(
    { editor: codeEditor, monaco }: MountedCodeEditor,
    handlers: NotebookJupyterEditorKeyHandlers
): () => void {
    const { KeyMod, KeyCode } = monaco
    const model = codeEditor.getModel()
    const language = model?.getLanguageId()
    const disposables: IDisposable[] = []
    let shownDocs: { text: string; position: IPosition } | null = null

    disposables.push(
        codeEditor.addAction({
            id: 'notebook-jupyter-tab',
            label: 'Complete or indent',
            keybindings: [KeyCode.Tab],
            precondition:
                'editorTextFocus && !editorReadonly && !suggestWidgetVisible && !inSnippetMode && !editorHasSelection && !editorHasMultipleSelections',
            run: (activeEditor) => {
                const activeModel = activeEditor.getModel()
                const position = activeEditor.getPosition()
                if (activeModel && position && CODE_BEFORE_CURSOR.test(textBeforeCursor(activeModel, position))) {
                    activeEditor.trigger('jupyter', 'editor.action.triggerSuggest', {})
                    return
                }
                activeEditor.trigger('keyboard', 'tab', null)
            },
        }),
        codeEditor.addAction({
            id: 'notebook-jupyter-leave-up',
            label: 'Move to the cell above at the first line',
            keybindings: [KeyCode.UpArrow],
            precondition: EDGE_KEY_PRECONDITION,
            run: (activeEditor) => {
                if (activeEditor.getPosition()?.lineNumber === 1) {
                    handlers.onLeaveCell('previous')
                    return
                }
                activeEditor.trigger('keyboard', 'cursorUp', null)
            },
        }),
        codeEditor.addAction({
            id: 'notebook-jupyter-leave-down',
            label: 'Move to the cell below at the last line',
            keybindings: [KeyCode.DownArrow],
            precondition: EDGE_KEY_PRECONDITION,
            run: (activeEditor) => {
                const lineCount = activeEditor.getModel()?.getLineCount() ?? 1
                if ((activeEditor.getPosition()?.lineNumber ?? 1) >= lineCount) {
                    handlers.onLeaveCell('next')
                    return
                }
                activeEditor.trigger('keyboard', 'cursorDown', null)
            },
        }),
        codeEditor.addAction({
            id: 'notebook-jupyter-delete-empty-cell',
            label: 'Delete the cell when it is empty',
            keybindings: [KeyCode.Backspace],
            precondition: 'editorTextFocus && !editorReadonly && !suggestWidgetVisible',
            run: (activeEditor) => {
                if (activeEditor.getModel()?.getValueLength() === 0) {
                    handlers.onDeleteEmptyCell()
                    return
                }
                activeEditor.trigger('keyboard', 'deleteLeft', null)
            },
        }),
        codeEditor.addAction({
            id: 'notebook-jupyter-split-cell',
            label: 'Split cell at cursor',
            // Jupyter uses Ctrl on every platform; Cmd is the macOS habit for the same chord.
            keybindings: [
                KeyMod.CtrlCmd | KeyMod.Shift | KeyCode.Minus,
                ...(isMac() ? [KeyMod.WinCtrl | KeyMod.Shift | KeyCode.Minus] : []),
            ],
            run: (activeEditor) => {
                const activeModel = activeEditor.getModel()
                const position = activeEditor.getPosition()
                if (activeModel && position) {
                    handlers.onSplit(activeModel.getOffsetAt(position))
                }
            },
        })
    )

    if (isMac()) {
        // Monaco binds commenting to Cmd+/ on macOS; Jupyter users also reach for Ctrl+/.
        disposables.push(
            codeEditor.addAction({
                id: 'notebook-jupyter-comment',
                label: 'Toggle line comment',
                keybindings: [KeyMod.WinCtrl | KeyCode.Slash],
                run: (activeEditor) => activeEditor.trigger('keyboard', 'editor.action.commentLine', null),
            })
        )
    }

    const { complete, inspect } = handlers
    if (complete && language) {
        disposables.push(
            monaco.languages.registerCompletionItemProvider(language, {
                triggerCharacters: ['.'],
                provideCompletionItems: async (requestModel: editor.ITextModel, position: IPosition) => {
                    // Providers are registered per language, so each cell answers only for its own editor.
                    if (requestModel !== codeEditor.getModel()) {
                        return { suggestions: [] }
                    }
                    const completions = await complete(requestModel.getValue(), requestModel.getOffsetAt(position))
                    if (!completions) {
                        return { suggestions: [] }
                    }
                    const start = requestModel.getPositionAt(completions.cursorStart)
                    const end = requestModel.getPositionAt(completions.cursorEnd)
                    const range = new monaco.Range(start.lineNumber, start.column, end.lineNumber, end.column)
                    return {
                        suggestions: completions.matches.map((match, index) => ({
                            label: match.text,
                            insertText: match.text,
                            kind: completionKind(monaco, match.type),
                            detail: match.type || undefined,
                            range,
                            // Keep the kernel's order: it ranks locals and attributes first.
                            sortText: String(index).padStart(5, '0'),
                        })),
                    }
                },
            })
        )
    }

    if (inspect && language) {
        disposables.push(
            monaco.languages.registerHoverProvider(language, {
                provideHover: (requestModel: editor.ITextModel, position: IPosition) => {
                    if (requestModel !== codeEditor.getModel() || !shownDocs) {
                        return null
                    }
                    const { text, position: docsPosition } = shownDocs
                    if (docsPosition.lineNumber !== position.lineNumber) {
                        return null
                    }
                    return {
                        range: new monaco.Range(
                            position.lineNumber,
                            position.column,
                            position.lineNumber,
                            position.column
                        ),
                        contents: [{ value: `\`\`\`\n${text}\n\`\`\`` }],
                    }
                },
            }),
            codeEditor.addAction({
                id: 'notebook-jupyter-docs',
                label: 'Show docs for the name at the cursor',
                keybindings: [KeyMod.Shift | KeyCode.Tab],
                precondition: 'editorTextFocus && !suggestWidgetVisible && !editorHasSelection',
                run: async (activeEditor) => {
                    const activeModel = activeEditor.getModel()
                    const position = activeEditor.getPosition()
                    if (
                        !activeModel ||
                        !position ||
                        !CODE_BEFORE_CURSOR.test(textBeforeCursor(activeModel, position))
                    ) {
                        activeEditor.trigger('keyboard', 'outdent', null)
                        return
                    }
                    const text = await inspect(activeModel.getValue(), activeModel.getOffsetAt(position))
                    if (!text) {
                        return
                    }
                    shownDocs = { text, position }
                    activeEditor.trigger('jupyter', 'editor.action.showHover', { focus: 'noAutoFocus' })
                },
            }),
            codeEditor.onDidChangeCursorPosition(() => {
                shownDocs = null
            })
        )
    }

    return () => disposables.forEach((disposable) => disposable.dispose())
}
