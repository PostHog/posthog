import { formatTraceIdsInput, parseTraceIdsInput } from './reviewQueueUtils'

describe('reviewQueueUtils', () => {
    it('parses trace IDs from mixed separators and removes duplicates', () => {
        expect(parseTraceIdsInput('trace_1, trace_2\ntrace_3   trace_2')).toEqual(['trace_1', 'trace_2', 'trace_3'])
    })

    it('formats trace IDs for textarea defaults', () => {
        expect(formatTraceIdsInput(['trace_1', 'trace_2'])).toBe('trace_1\ntrace_2')
    })
})
