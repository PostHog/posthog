import { CaptureResult } from 'posthog-js'

import { dropExtensionOriginExceptions } from './dropExtensionExceptions'

const APP_FRAME = { filename: 'https://us-assets.i.posthog.com/static/chunk-ABC123.js', function: 'render' }
const JAM_FRAME = { filename: 'webpack://jam-extension/injected-scripts/host-network-events.js', function: '?' }
const CHROME_FRAME = { filename: 'chrome-extension://abcdef/content.js', function: 'handler' }
const MASKED_FRAME = { filename: 'webkit-masked-url://hidden/', function: 'global code' }

const exceptionEvent = (frames: Record<string, unknown>[]): CaptureResult =>
    ({
        event: '$exception',
        properties: { $exception_list: [{ type: 'Error', stacktrace: { frames } }] },
    }) as unknown as CaptureResult

describe('dropExtensionOriginExceptions', () => {
    it.each([
        // The reported case: every frame comes from a webpack-bundled extension.
        ['webpack extension bundle', [JAM_FRAME, JAM_FRAME], null],
        ['chrome extension scheme', [CHROME_FRAME], null],
        // A real app fault keeps at least one served frame, even alongside an extension frame.
        ['mixed extension and app frames', [JAM_FRAME, APP_FRAME], 'keep'],
        ['app frames only', [APP_FRAME], 'keep'],
        // Without frames there is nothing to attribute to an extension.
        ['no frames', [], 'keep'],
        // Safari masks the page's own scripts the same way it masks extension scripts, so an
        // all-masked stack that posthog-js chose to forward is a genuine app exception.
        ['safari masked urls only', [MASKED_FRAME, MASKED_FRAME], 'keep'],
    ])('%s', (_label, frames, expected) => {
        const event = exceptionEvent(frames)
        expect(dropExtensionOriginExceptions(event)).toBe(expected === null ? null : event)
    })

    it('keeps events that are not exceptions', () => {
        const event = { event: '$pageview', properties: {} } as unknown as CaptureResult
        expect(dropExtensionOriginExceptions(event)).toBe(event)
    })
})
