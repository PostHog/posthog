import { TraceListRow, uniqueTraces } from './traceListRows'

describe('traceListRows', () => {
    it('keeps the first row of each trace, in order of first appearance', () => {
        const rows: TraceListRow[] = [
            { traceId: 'a', timestamp: null, stepId: 'x' },
            { traceId: 'b', timestamp: null, stepId: null },
            { traceId: 'a', timestamp: null, stepId: 'y' },
        ]

        expect(uniqueTraces(rows)).toEqual([rows[0], rows[1]])
    })
})
