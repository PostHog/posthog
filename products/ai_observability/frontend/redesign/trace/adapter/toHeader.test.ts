import { makeTrace } from './testFixtures'
import { TraceNeighbours, toHeader } from './toHeader'

const noNeighbours: TraceNeighbours = {
    olderTraceId: null,
    olderTimestamp: null,
    newerTraceId: null,
    newerTimestamp: null,
}

describe('toHeader', () => {
    it('links neighbours with their timestamps and the list context, and leaves missing neighbours null', () => {
        const header = toHeader(
            makeTrace(),
            { ...noNeighbours, olderTraceId: 'trace-0', olderTimestamp: '2026-09-01T10:00:00Z' },
            { date_from: '-7d', event: 'gen-1', line: '4', back_to: 'generations' }
        )
        expect(header.olderHref).toBe(
            '/ai-observability/traces/trace-0?date_from=-7d&timestamp=2026-09-01T10%3A00%3A00Z'
        )
        expect(header.newerHref).toBeNull()
    })

    it.each([
        [
            'the traces list by default, keeping its filters',
            { date_from: '-7d', event: 'gen-1' },
            '/ai-observability/traces?date_from=-7d',
        ],
        [
            'the generations list when opened from it',
            { back_to: 'generations', date_from: '-7d', tab: 'evals' },
            '/ai-observability/generations?date_from=-7d',
        ],
        [
            'the reviews tab when opened from reviews',
            { back_to: 'reviews' },
            '/ai-observability/reviews?human_reviews_tab=reviews',
        ],
        [
            'the review queue when opened from one',
            { back_to: 'reviews', queue_id: 'queue-1' },
            '/ai-observability/reviews?queue_id=queue-1',
        ],
    ])('goes back to %s', (_name, searchParams, expected) => {
        expect(toHeader(makeTrace(), noNeighbours, searchParams).backLink.href).toBe(expected)
    })

    it.each([
        ['a named trace keeps its name', 'answer-billing-question', 'answer-billing-question'],
        ['an unnamed trace gets a fallback distinct from the Trace badge', undefined, 'Untitled trace'],
    ])('%s', (_name, traceName, expected) => {
        expect(toHeader(makeTrace({ traceName }), noNeighbours, {}).name).toBe(expected)
    })
})
