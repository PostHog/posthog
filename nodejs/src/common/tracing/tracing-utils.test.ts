import { linksFromTraceparents, spanContextFromTraceparent } from './tracing-utils'

const SPAN_ID = 'b7ad6b7169203331'

function traceparent(traceId: string, flags: string = '01'): string {
    return `00-${traceId}-${SPAN_ID}-${flags}`
}

function traceId(index: number): string {
    return (index + 1).toString(16).padStart(32, '0')
}

describe('tracing-utils trace links', () => {
    describe('spanContextFromTraceparent', () => {
        it('parses a well-formed sampled traceparent', () => {
            const result = spanContextFromTraceparent(traceparent('0af7651916cd43dd8448eb211c80319c'))
            expect(result).toEqual({
                traceId: '0af7651916cd43dd8448eb211c80319c',
                spanId: SPAN_ID,
                traceFlags: 1,
                isRemote: true,
            })
        })

        it.each([
            ['malformed string', 'not-a-traceparent'],
            ['all-zero trace id', traceparent('0'.repeat(32))],
            ['wrong trace id length', `00-abc-${SPAN_ID}-01`],
        ])('returns null for %s', (_label, value) => {
            expect(spanContextFromTraceparent(value)).toBeNull()
        })
    })

    describe('linksFromTraceparents', () => {
        it('dedupes multiple events sharing one capture trace', () => {
            const shared = traceparent(traceId(0))
            const links = linksFromTraceparents([shared, shared, shared])
            expect(links).toHaveLength(1)
            expect(links[0].context.traceId).toBe(traceId(0))
        })

        it('skips unsampled traces so links do not dangle', () => {
            const links = linksFromTraceparents([traceparent(traceId(0), '00'), traceparent(traceId(1), '01')])
            expect(links.map((link) => link.context.traceId)).toEqual([traceId(1)])
        })

        it('caps links at the per-span limit', () => {
            const traceparents = Array.from({ length: 130 }, (_, i) => traceparent(traceId(i)))
            expect(linksFromTraceparents(traceparents)).toHaveLength(128)
        })
    })
})
