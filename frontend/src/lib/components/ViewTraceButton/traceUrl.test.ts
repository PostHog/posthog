import { traceUrl } from './traceUrl'

describe('traceUrl', () => {
    it.each([
        [{ traceId: 'abc123' }, '/tracing?trace=abc123'],
        [{ traceId: 'abc123', spanId: 'def456' }, '/tracing?trace=abc123&span=def456'],
        [
            { traceId: 'abc123', spanId: 'def456', ts: '2026-06-11T08:00:00.000Z' },
            '/tracing?trace=abc123&span=def456&ts=2026-06-11T08%3A00%3A00.000Z',
        ],
        // Null/undefined anchor and hint are simply omitted.
        [{ traceId: 'abc123', spanId: null, ts: null }, '/tracing?trace=abc123'],
    ])('traceUrl(%j) → %s', (params, expected) => {
        expect(traceUrl(params)).toBe(expected)
    })
})
