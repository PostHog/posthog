import { createEvent } from '@posthog/plugin-scaffold/test/utils'

import { onEvent, PatternsMeta, setupPlugin } from './index'

const testWebhookUrl = 'https://api-staging.patterns.app/api/app/webhooks/wh1234'

describe('Patterns: onEvent', () => {
    const fetchMock = jest.fn()

    beforeEach(() => {
        fetchMock.mockReset()

        fetchMock.mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({}),
        })
    })

    test('onEvent called for event', async () => {
        const meta = {
            config: {
                webhookUrl: testWebhookUrl,
            },
            global: {},
            fetch: fetchMock as unknown,
        } as PatternsMeta
        void setupPlugin(meta)
        const event1 = createEvent({ event: '$pageView' })

        await onEvent(event1, meta)

        expect(fetchMock.mock.calls.length).toEqual(1)
        expect(fetchMock.mock.calls[0][0]).toEqual(testWebhookUrl)
        expect(fetchMock.mock.calls[0][1]).toEqual({
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
            fetch: fetchMock as unknown,
        } as PatternsMeta
        void setupPlugin(meta)

        const event = createEvent({ event: '$pageView' })
        void (await onEvent(event, meta))
        expect(fetchMock.mock.calls.length).toEqual(1)
        expect(fetchMock.mock.calls[0][0]).toEqual(testWebhookUrl)
        expect(fetchMock.mock.calls[0][1]).toEqual({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify([event]),
        })

        const event2 = createEvent({ event: '$pageLeave' })
        await onEvent(event2, meta)
        expect(fetchMock.mock.calls.length).toEqual(1)
    })
})
