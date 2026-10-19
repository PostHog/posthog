import { traceUrl } from './traceUrl'

describe('traceUrl', () => {
    it.each([
        [{ traceId: 'abc123' }, '/tracing?trace=ABC123'],
        [{ traceId: 'abc123', spanId: 'def456' }, '/tracing?trace=ABC123&span=DEF456'],
        [
            { traceId: 'abc123', spanId: 'def456', ts: '2026-06-11T08:00:00.000Z' },
            '/tracing?trace=ABC123&span=DEF456&ts=2026-06-11T08%3A00%3A00.000Z',
        ],
        [
            { traceId: 'abc123', spanId: 'ai:0190a1b2-0000-7000-8000-000000000001' },
            '/tracing?trace=ABC123&span=ai%3A0190a1b2-0000-7000-8000-000000000001',
        ],
        // Null/undefined anchor and hint are simply omitted.
        [{ traceId: 'abc123', spanId: null, ts: null }, '/tracing?trace=ABC123'],
    ])('traceUrl(%j) → %s', (params, expected) => {
        expect(traceUrl(params)).toBe(expected)
    })
})
