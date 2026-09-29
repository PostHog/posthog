import { makeTrace } from './testFixtures'
import { toHeader } from './toHeader'

describe('toHeader', () => {
    it('links neighbours with their timestamps, and leaves missing neighbours null', () => {
        const header = toHeader(makeTrace(), {
            olderTraceId: 'trace-0',
            olderTimestamp: '2026-09-01T10:00:00Z',
            newerTraceId: null,
            newerTimestamp: null,
        })
        expect(header.olderHref).toContain('/ai-observability/traces/trace-0')
        expect(header.olderHref).toContain('timestamp=2026-09-01T10%3A00%3A00Z')
        expect(header.newerHref).toBeNull()
        expect(header.backHref).toBe('/ai-observability/traces')
    })
    it.each([
        ['a named trace keeps its name', 'answer-billing-question', 'answer-billing-question'],
        ['an unnamed trace gets a fallback distinct from the Trace badge', undefined, 'Untitled trace'],
    ])('%s', (_name, traceName, expected) => {
        const noNeighbours = { olderTraceId: null, olderTimestamp: null, newerTraceId: null, newerTimestamp: null }
        expect(toHeader(makeTrace({ traceName }), noNeighbours).name).toBe(expected)
    })
})
