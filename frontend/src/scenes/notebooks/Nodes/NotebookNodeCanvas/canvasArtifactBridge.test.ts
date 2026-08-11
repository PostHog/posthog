import {
    CanvasCapabilities,
    assertCanvasCapability,
    createCanvasHostMessageRouter,
    parseCanvasCapabilities,
} from './canvasArtifactBridge'

describe('canvasArtifactBridge', () => {
    const capabilities: CanvasCapabilities = {
        posthog: {
            inlineQueries: false,
            insights: ['abc123'],
            captureEvents: ['canvas_clicked'],
        },
    }

    it.each([
        ['query denied when inline queries are off', capabilities, 'query', {}, false],
        [
            'query allowed when inline queries are on',
            { posthog: { ...capabilities.posthog, inlineQueries: true } },
            'query',
            {},
            true,
        ],
        ['allowlisted insight allowed', capabilities, 'loadInsight', { shortId: 'abc123' }, true],
        ['non-allowlisted insight denied', capabilities, 'loadInsight', { shortId: 'other' }, false],
        ['allowlisted capture event allowed', capabilities, 'capture', { event: 'canvas_clicked' }, true],
        ['non-allowlisted capture event denied', capabilities, 'capture', { event: 'other_event' }, false],
        ['unknown method denied', capabilities, 'run', {}, false],
        ['missing manifest denies everything', undefined, 'loadInsight', { shortId: 'abc123' }, false],
    ] as [string, CanvasCapabilities | undefined, string, unknown, boolean][])(
        '%s',
        (_label, caps, method, payload, allowed) => {
            const call = (): void => assertCanvasCapability(caps, method, payload)
            if (allowed) {
                expect(call).not.toThrow()
            } else {
                expect(call).toThrow()
            }
        }
    )

    it.each([
        ['null manifest', null, undefined],
        ['manifest without posthog block', { network: {} }, undefined],
        [
            'malformed lists are dropped instead of trusted',
            { posthog: { inlineQueries: 'yes', insights: 'abc', captureEvents: [1, 'ok'] } },
            { posthog: { inlineQueries: false, insights: [], captureEvents: ['ok'] } },
        ],
    ] as [string, unknown, CanvasCapabilities | undefined][])('parses capabilities: %s', (_label, raw, expected) => {
        expect(parseCanvasCapabilities(raw)).toEqual(expected)
    })

    it('keeps timed-out requests in the concurrency limit until their work finishes', async () => {
        jest.useFakeTimers()
        const post = jest.fn()
        const pending: Array<(value: unknown) => void> = []
        const onDataRequest = jest.fn(
            () =>
                new Promise((resolve) => {
                    pending.push(resolve)
                })
        )
        const route = createCanvasHostMessageRouter(post, () => ({ onDataRequest }))
        const requests = Array.from({ length: 8 }, (_, index) =>
            route({
                channel: 'posthog-canvas',
                type: 'data-request',
                id: `request-${index}`,
                method: 'query',
                payload: {},
            })
        )

        await Promise.resolve()
        expect(onDataRequest).toHaveBeenCalledTimes(8)

        await jest.advanceTimersByTimeAsync(30_000)
        await route({
            channel: 'posthog-canvas',
            type: 'data-request',
            id: 'request-9',
            method: 'query',
            payload: {},
        })

        expect(onDataRequest).toHaveBeenCalledTimes(8)
        expect(post).toHaveBeenCalledWith({
            channel: 'posthog-canvas',
            type: 'data-response',
            id: 'request-9',
            ok: false,
            error: 'Canvas data request exceeds runtime limits',
        })

        pending.forEach((resolve) => resolve(null))
        await Promise.all(requests)
        jest.useRealTimers()
    })
})
