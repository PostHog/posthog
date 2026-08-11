import type { editor, IRange } from 'monaco-editor'

import { renderQueryOutline } from './sqlEditorLogic'

const LINE_HEIGHT = 18

// Minimal Monaco stand-in whose `getLineMaxColumn` throws for out-of-range lines,
// exactly like the real editor: that throw ("Illegal value for lineNumber") is the
// crash we're guarding against when a paste/edit shrinks the model under a stale range.
function makeEditor(
    lineCount: number,
    visibleRanges?: { startLineNumber: number; endLineNumber: number }[]
): { editorInstance: editor.IStandaloneCodeEditor; getScrolledVisiblePosition: jest.Mock } {
    const model = {
        getLineCount: () => lineCount,
        getLineMaxColumn: (line: number) => {
            if (line < 1 || line > lineCount) {
                throw new Error('Illegal value for lineNumber')
            }
            return 20
        },
    }
    const getScrolledVisiblePosition = jest.fn(() => ({ left: 0, top: 0, height: LINE_HEIGHT }))
    const editorInstance = {
        getModel: () => model,
        getScrolledVisiblePosition,
        getScrollTop: () => 0,
        getTopForPosition: (line: number) => (line - 1) * LINE_HEIGHT,
        getBottomForLineNumber: (line: number) => line * LINE_HEIGHT,
        ...(visibleRanges ? { getVisibleRanges: () => visibleRanges } : {}),
    } as unknown as editor.IStandaloneCodeEditor

    return { editorInstance, getScrolledVisiblePosition }
}

describe('renderQueryOutline', () => {
    it('does not throw when the cached range points past a shrunk model', () => {
        const node = document.createElement('div')
        // Model has 2 lines, but the cached range still spans 5 (e.g. after a paste removed lines).
        const staleRange: IRange = { startLineNumber: 1, startColumn: 1, endLineNumber: 5, endColumn: 10 }
        const { editorInstance } = makeEditor(2)

        expect(() => renderQueryOutline(editorInstance, node, staleRange)).not.toThrow()
        expect(node.style.display).toBe('block')
    })

    it('only measures rendered lines, not the whole range', () => {
        const node = document.createElement('div')
        // A 900-line statement with only ~10 lines on screen: measuring every line would
        // force a synchronous Monaco view render per call, which is what made scrolling lag.
        const { editorInstance, getScrolledVisiblePosition } = makeEditor(900, [
            { startLineNumber: 400, endLineNumber: 409 },
        ])
        const range: IRange = { startLineNumber: 1, startColumn: 1, endLineNumber: 900, endColumn: 10 }

        renderQueryOutline(editorInstance, node, range)

        // Two calls per visible line, and nothing for the 890 off-screen ones.
        expect(getScrolledVisiblePosition).toHaveBeenCalledTimes(20)
        expect(node.style.display).toBe('block')
    })

    it('spans the full range vertically even when most of it is off screen', () => {
        const node = document.createElement('div')
        const { editorInstance } = makeEditor(900, [{ startLineNumber: 400, endLineNumber: 409 }])
        const range: IRange = { startLineNumber: 1, startColumn: 1, endLineNumber: 900, endColumn: 10 }

        renderQueryOutline(editorInstance, node, range)

        // Vertical extent comes from layout math over the whole range, so it isn't clamped
        // to the viewport the way the horizontal measurement is.
        expect(node.style.top).toBe('-1px')
        expect(node.style.height).toBe(`${900 * LINE_HEIGHT + 2}px`)
    })

    it('hides the overlay when no rendered line intersects the range', () => {
        const node = document.createElement('div')
        const { editorInstance, getScrolledVisiblePosition } = makeEditor(900, [
            { startLineNumber: 800, endLineNumber: 809 },
        ])
        const range: IRange = { startLineNumber: 1, startColumn: 1, endLineNumber: 100, endColumn: 10 }

        renderQueryOutline(editorInstance, node, range)

        expect(getScrolledVisiblePosition).not.toHaveBeenCalled()
        expect(node.style.display).toBe('none')
    })
})
