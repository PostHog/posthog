import { type CaptureResult } from 'posthog-js'

import { dedupeChunkLoadExceptions } from './dedupeChunkLoadExceptions'

function exceptionEvent(type: string, value: string): CaptureResult {
    return {
        event: '$exception',
        properties: { $exception_list: [{ type, value }] },
    } as unknown as CaptureResult
}

describe('dedupeChunkLoadExceptions', () => {
    const CHUNK_MESSAGE = 'Failed to fetch dynamically imported module: /static/foo.js'

    it('keeps the first chunk-load exception but drops synchronous repeats of the same error', () => {
        const beforeSend = dedupeChunkLoadExceptions()
        const first = exceptionEvent('TypeError', CHUNK_MESSAGE)
        const second = exceptionEvent('TypeError', CHUNK_MESSAGE)

        // One chunk failure rethrown through two nested boundaries → two identical captures in one task.
        expect(beforeSend(first)).toBe(first)
        expect(beforeSend(second)).toBeNull()
    })

    it('keeps distinct chunk-load failures (different messages) even in the same task', () => {
        const beforeSend = dedupeChunkLoadExceptions()
        const a = exceptionEvent('TypeError', 'Failed to fetch dynamically imported module: /static/a.js')
        const b = exceptionEvent('TypeError', 'Failed to fetch dynamically imported module: /static/b.js')

        expect(beforeSend(a)).toBe(a)
        expect(beforeSend(b)).toBe(b)
    })

    it('re-reports the same chunk error once the task settles', async () => {
        const beforeSend = dedupeChunkLoadExceptions()
        const first = exceptionEvent('TypeError', CHUNK_MESSAGE)
        const later = exceptionEvent('TypeError', CHUNK_MESSAGE)

        expect(beforeSend(first)).toBe(first)
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(beforeSend(later)).toBe(later)
    })

    it('passes through non-chunk exceptions untouched, including repeats', () => {
        const beforeSend = dedupeChunkLoadExceptions()
        const a = exceptionEvent('Error', 'regular render failure')
        const b = exceptionEvent('Error', 'regular render failure')

        expect(beforeSend(a)).toBe(a)
        expect(beforeSend(b)).toBe(b)
    })

    it('passes through non-exception events and null', () => {
        const beforeSend = dedupeChunkLoadExceptions()
        const pageview = { event: '$pageview', properties: {} } as unknown as CaptureResult

        expect(beforeSend(pageview)).toBe(pageview)
        expect(beforeSend(null)).toBeNull()
    })
})
