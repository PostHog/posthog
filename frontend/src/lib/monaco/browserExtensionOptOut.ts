import type { editor } from 'monaco-editor'

// Grammar checkers and password managers attach to editable elements and run work on every keystroke. Each
// attribute below is the documented opt-out for one of them. Monaco takes input through a textarea, or through an
// EditContext element in browsers that support it, so both get the attributes.
const OPT_OUT_ATTRIBUTES: Record<string, string> = {
    spellcheck: 'false',
    autocorrect: 'off',
    autocapitalize: 'off',
    'data-gramm': 'false',
    'data-gramm_editor': 'false',
    'data-enable-grammarly': 'false',
    'data-lt-active': 'false',
    'data-1p-ignore': 'true',
    'data-lpignore': 'true',
    'data-bwignore': 'true',
    'data-form-type': 'other',
}

export function optOutOfBrowserExtensions(codeEditor: editor.ICodeEditor): void {
    const root = codeEditor.getDomNode()
    if (!root) {
        return
    }
    for (const element of [root, ...root.querySelectorAll('textarea, .native-edit-context')]) {
        for (const [name, value] of Object.entries(OPT_OUT_ATTRIBUTES)) {
            element.setAttribute(name, value)
        }
    }
}
