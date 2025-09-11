import { createEvent } from '@posthog/plugin-scaffold/test/utils'

import { PatternsMeta, onEvent, setupPlugin } from './index'

const testWebhookUrl = 'https://api-staging.patterns.app/api/app/webhooks/wh1234'

describe('Patterns: onEvent', () => {
    const mockRequest = jest.fn()

    beforeEach(() => {
        mockRequest.mockReset()

        mockRequest.mockResolvedValue({
            status: 200,
            body: JSON.stringify({}),
            headers: {},
        })
    })

    test('onEvent called for event', async () => {
        const meta = {
            config: {
                webhookUrl: testWebhookUrl,
            },
            global: {},
            fetch: mockRequest as unknown,
        } as PatternsMeta
        void setupPlugin(meta)
        const event1 = createEvent({ event: '$pageView' })

        await onEvent(event1, meta)

        expect(mockRequest.mock.calls.length).toEqual(1)
        expect(mockRequest.mock.calls[0][0]).toEqual(testWebhookUrl)
        expect(mockRequest.mock.calls[0][1]).toEqual({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify([event1]),
        })
    })

    test('onEvent called for allowed event', async () => {
        const meta = {
            config: {
                webhookUrl: testWebhookUrl,
                allowedEventTypes: '$pageView, $autoCapture, $customEvent1',
            },
            global: {},
            fetch: mockRequest as unknown,
        } as PatternsMeta
        void setupPlugin(meta)

        const event = createEvent({ event: '$pageView' })
        void (await onEvent(event, meta))
        expect(mockRequest.mock.calls.length).toEqual(1)
        expect(mockRequest.mock.calls[0][0]).toEqual(testWebhookUrl)
        expect(mockRequest.mock.calls[0][1]).toEqual({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify([event]),
        })

        const event2 = createEvent({ event: '$pageLeave' })
        await onEvent(event2, meta)
        expect(mockRequest.mock.calls.length).toEqual(1)
    })
})
