import posthog, { CaptureResult } from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { dropBrowserExtensionExceptions, isInDeferredInitSample, loadPostHogJS } from './loadPostHogJS'

const documentUrl = window.location.origin + window.location.pathname
const bundleUrl = `${window.location.origin}/static/chunk-abc123.js`

const exceptionEvent = (frames: Record<string, unknown>[]): CaptureResult =>
    ({
        event: '$exception',
        properties: { $exception_list: [{ type: 'TypeError', stacktrace: { type: 'raw', frames } }] },
    }) as unknown as CaptureResult

describe('loadPostHogJS', () => {
    describe('dropBrowserExtensionExceptions', () => {
        it.each([
            ['one global code frame at line 1', [{ filename: documentUrl, function: 'global code', lineno: 1 }]],
            [
                'two minified WebKit frames at line 17',
                [
                    { filename: documentUrl, function: '?', lineno: 17, colno: 5021 },
                    { filename: `${documentUrl}?q=1#top`, function: 'r', lineno: 17, colno: 812 },
                ],
            ],
        ])('drops an exception with %s on the document URL', (_, frames) => {
            expect(dropBrowserExtensionExceptions(exceptionEvent(frames))).toBeNull()
        })

        it.each([
            ['the document URL the page loaded with', documentUrl],
            ['the current document URL', `${window.location.origin}/project/1/insights`],
        ])('drops an exception on %s after a route change', (_, filename) => {
            window.history.pushState({}, '', '/project/1/insights')
            try {
                const frames = [{ filename, function: '?', lineno: 17 }]
                expect(dropBrowserExtensionExceptions(exceptionEvent(frames))).toBeNull()
            } finally {
                window.history.pushState({}, '', documentUrl)
            }
        })

        it.each([
            ['only bundle frames', [{ filename: bundleUrl, function: 'render', lineno: 42 }]],
            [
                'a bundle frame among document URL frames',
                [
                    { filename: documentUrl, function: '?', lineno: 17 },
                    { filename: bundleUrl, function: 'render', lineno: 42 },
                ],
            ],
            ['no frames', []],
        ])('keeps an exception with %s', (_, frames) => {
            const event = exceptionEvent(frames)
            expect(dropBrowserExtensionExceptions(event)).toBe(event)
        })

        it('keeps events that are not exceptions', () => {
            const event = { event: '$pageview', properties: {} } as unknown as CaptureResult
            expect(dropBrowserExtensionExceptions(event)).toBe(event)
        })
    })

    describe('isInDeferredInitSample', () => {
        it.each(['', 'a', '0198f1e2-9c3b-7a1d-8f4e-2b6c9d0e1f23', 'session-one', 'session-two', 'session-three'])(
            'keeps the posthog-js sampling verdict for session %p',
            (sessionId) => {
                expect(isInDeferredInitSample(sessionId)).toBe(sampleOnProperty(sessionId, 0.5))
            }
        )
    })

    describe('without a project key', () => {
        it('starts posthog-js with no request to PostHog', () => {
            window.JS_POSTHOG_API_KEY = undefined

            loadPostHogJS()

            expect(posthog.init).toHaveBeenCalledWith(
                'fake_token',
                expect.objectContaining({ advanced_disable_flags: true, opt_out_capturing_by_default: true })
            )
        })
    })
})
