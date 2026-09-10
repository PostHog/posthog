import { CaptureResult } from 'posthog-js'

import { dropBrowserExtensionExceptions } from './browserExtensionExceptions'

const documentUrl = (): string => window.location.origin + window.location.pathname

const exceptionEvent = (frames: Record<string, unknown>[]): CaptureResult =>
    ({
        event: '$exception',
        properties: { $exception_list: [{ type: 'TypeError', stacktrace: { frames } }] },
    }) as unknown as CaptureResult

describe('dropBrowserExtensionExceptions', () => {
    it('drops an exception thrown by a script injected into the page', () => {
        const event = exceptionEvent([{ filename: documentUrl(), function: 'global code', lineno: 1 }])
        expect(dropBrowserExtensionExceptions(event)).toBeNull()
    })

    it('keeps an exception thrown by one of our own script files', () => {
        const event = exceptionEvent([
            { filename: `${window.location.origin}/static/chunk.js`, function: 'render', lineno: 42 },
        ])
        expect(dropBrowserExtensionExceptions(event)).toBe(event)
    })

    it('keeps an exception with more than one frame', () => {
        const event = exceptionEvent([
            { filename: documentUrl(), function: 'global code', lineno: 1 },
            { filename: `${window.location.origin}/static/chunk.js`, function: 'render', lineno: 42 },
        ])
        expect(dropBrowserExtensionExceptions(event)).toBe(event)
    })

    it('keeps events that are not exceptions', () => {
        const event = { event: '$pageview', properties: {} } as unknown as CaptureResult
        expect(dropBrowserExtensionExceptions(event)).toBe(event)
    })
})
