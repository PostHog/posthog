import { traceUrl } from './traceUrl'

describe('traceUrl', () => {
    it.each([
        [{ traceId: 'abc123' }, '/tracing?trace=ABC123'],
        [{ traceId: 'abc123', spanId: 'def456' }, '/tracing?trace=ABC123&span=DEF456'],
        [
            { traceId: 'abc123', spanId: 'def456', ts: '2026-06-11T08:00:00.000Z' },
            '/tracing?trace=ABC123&span=DEF456&ts=2026-06-11T08%3A00%3A00.000Z',
        ],
        // Null/undefined anchor and hint are simply omitted.
        [{ traceId: 'abc123', spanId: null, ts: null }, '/tracing?trace=ABC123'],
    ])('traceUrl(%j) → %s', (params, expected) => {
        expect(traceUrl(params)).toBe(expected)
    })
})
