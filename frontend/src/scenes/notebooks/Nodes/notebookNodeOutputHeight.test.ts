import { countTextLines, initialSizedRunId, outputHeightForShape } from './notebookNodeOutputHeight'

describe('notebookNodeOutputHeight', () => {
    it('returns null when there is nothing to show', () => {
        expect(outputHeightForShape({})).toBeNull()
        expect(outputHeightForShape({ rowCount: 0, textLines: 0, hasMedia: false })).toBeNull()
    })

    it('keeps a single-value result compact', () => {
        const oneRow = outputHeightForShape({ rowCount: 1 })
        const fiveRows = outputHeightForShape({ rowCount: 5 })
        expect(oneRow).toBeLessThan(fiveRows!)
        expect(oneRow).toBeLessThan(250)
    })

    it('grows with the row count and caps out', () => {
        const heights = [1, 5, 10, 50, 1000].map((rowCount) => outputHeightForShape({ rowCount })!)
        expect(heights).toEqual([...heights].sort((a, b) => a - b))
        expect(heights.at(-1)).toEqual(outputHeightForShape({ rowCount: 50 }))
    })

    it('caps long text output so a traceback cannot swallow the notebook', () => {
        expect(outputHeightForShape({ textLines: 500 })).toEqual(outputHeightForShape({ textLines: 1000 }))
    })

    it('leaves room for a figure', () => {
        expect(outputHeightForShape({ hasMedia: true })!).toBeGreaterThan(outputHeightForShape({ textLines: 1 })!)
    })

    it.each([
        // An MCP run writes the envelope into the markdown but no height, so the cell arrives
        // with a result it has never been sized for.
        { when: 'a result that arrived without a height', hasResult: true, height: undefined, runId: 'run-1' },
        { when: 'no result yet', hasResult: false, height: undefined, runId: null },
    ])('treats $when as needing sizing', ({ hasResult, height, runId }) => {
        expect(initialSizedRunId({ hasResult, height, runId })).toBeUndefined()
    })

    it('leaves a cell the editor already sized alone', () => {
        expect(initialSizedRunId({ hasResult: true, height: 300, runId: 'run-1' })).toEqual('run-1')
    })

    it('counts text lines across streams, ignoring a trailing newline', () => {
        expect(countTextLines('a\nb\n', 'c')).toEqual(3)
        expect(countTextLines(null, undefined, '')).toEqual(0)
    })
})
