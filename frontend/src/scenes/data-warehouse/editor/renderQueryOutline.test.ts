import type { editor, IRange } from 'monaco-editor'

import { renderQueryOutline } from './sqlEditorLogic'

// Minimal Monaco stand-in whose `getLineMaxColumn` throws for out-of-range lines,
// exactly like the real editor: that throw ("Illegal value for lineNumber") is the
// crash we're guarding against when a paste/edit shrinks the model under a stale range.
function makeEditor(lineCount: number): editor.IStandaloneCodeEditor {
    const model = {
        getLineCount: () => lineCount,
        getLineMaxColumn: (line: number) => {
            if (line < 1 || line > lineCount) {
                throw new Error('Illegal value for lineNumber')
            }
            return 20
        },
    }
    return {
        getModel: () => model,
        getScrolledVisiblePosition: () => ({ left: 0, top: 0, height: 18 }),
    } as unknown as editor.IStandaloneCodeEditor
}

describe('renderQueryOutline', () => {
    it('does not throw when the cached range points past a shrunk model', () => {
        const node = document.createElement('div')
        // Model has 2 lines, but the cached range still spans 5 (e.g. after a paste removed lines).
        const staleRange: IRange = { startLineNumber: 1, startColumn: 1, endLineNumber: 5, endColumn: 10 }

        expect(() => renderQueryOutline(makeEditor(2), node, staleRange)).not.toThrow()
        expect(node.style.display).toBe('block')
    })
})
