import { CaptureResult } from 'posthog-js'

import { dropInjectedScriptExceptions } from './loadPostHogJS'

const exceptionEvent = (frames: { filename?: string }[]): CaptureResult =>
    ({
        event: '$exception',
        properties: { $exception_list: [{ stacktrace: { frames } }] },
    }) as unknown as CaptureResult

describe('dropInjectedScriptExceptions', () => {
    const appFrame = { filename: 'https://app-static-prod.posthog.com/static/chunk-AJSH7EWR.js' }
    const documentFrame = { filename: 'https://eu.posthog.com/project/271487/onboarding' }

    it('drops an exception whose frames all belong to the document', () => {
        expect(dropInjectedScriptExceptions(exceptionEvent([documentFrame, documentFrame]))).toBeNull()
    })

    it.each([
        ['a bundle chunk', appFrame],
        ['a cache-busted bundle', { filename: 'https://eu.posthog.com/static/index.js?t=1789073709923' }],
        ['a source file in dev', { filename: 'http://localhost:8234/src/scenes/onboarding/Onboarding.tsx' }],
    ])('keeps an exception with a frame from %s', (_label, frame) => {
        const event = exceptionEvent([documentFrame, frame])
        expect(dropInjectedScriptExceptions(event)).toBe(event)
    })

    it.each([
        ['an exception with no frames', exceptionEvent([])],
        ['a non-exception event', { event: '$pageview', properties: {} } as unknown as CaptureResult],
    ])('keeps %s', (_label, event) => {
        expect(dropInjectedScriptExceptions(event)).toBe(event)
    })
})
