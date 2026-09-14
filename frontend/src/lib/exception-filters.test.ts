import { CaptureResult } from 'posthog-js'

import { dropUnhandledAbortExceptions } from './exception-filters'

describe('dropUnhandledAbortExceptions', () => {
    const exceptionEvent = (exceptions: unknown[]): CaptureResult => ({
        uuid: 'a5c4d0ee-2b0a-4f0f-9a1a-0f7f6a3b1c2d',
        event: '$exception',
        properties: { $exception_list: exceptions },
    })

    it.each([
        ['DOMException', 'AbortError: The operation was aborted. '],
        ['DOMException', 'AbortError: signal is aborted without reason'],
        ['AbortError', 'Fetch is aborted'],
    ])('drops an unhandled %s carrying %p', (type, value) => {
        expect(
            dropUnhandledAbortExceptions(exceptionEvent([{ type, value, mechanism: { handled: false } }]))
        ).toBeNull()
    })

    it('keeps an abort a caller reported on purpose', () => {
        const event = exceptionEvent([
            { type: 'DOMException', value: 'AbortError: The operation was aborted. ', mechanism: { handled: true } },
        ])
        expect(dropUnhandledAbortExceptions(event)).toBe(event)
    })

    it('keeps an unhandled failure that is not an abort', () => {
        const event = exceptionEvent([
            { type: 'TypeError', value: 'x is not a function', mechanism: { handled: false } },
        ])
        expect(dropUnhandledAbortExceptions(event)).toBe(event)
    })

    it('keeps an event that is not an exception', () => {
        const event: CaptureResult = {
            uuid: '9f2b1c3d-4e5f-4a6b-8c7d-1e2f3a4b5c6d',
            event: '$pageview',
            properties: {},
        }
        expect(dropUnhandledAbortExceptions(event)).toBe(event)
    })
})
