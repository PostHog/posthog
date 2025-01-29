import { createEvent } from '@posthog/plugin-scaffold/test/utils'
import fetchMock from 'jest-fetch-mock'

fetchMock.enableMocks()

import { PatternsMeta, onEvent, setupPlugin } from './index'

const testWebhookUrl = 'https://api-staging.patterns.app/api/app/webhooks/wh1234'

beforeEach(() => {
    fetchMock.resetMocks()
})

test('onEvent called for event', async () => {
    let meta = {
        config: {
            webhookUrl: testWebhookUrl,
        },
        global: {},
        fetch: fetchMock as unknown,
    } as PatternsMeta
    setupPlugin(meta)
    const event1 = createEvent({ event: '$pageView' })

    // @ts-ignore
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
    let meta = {
        config: {
            webhookUrl: testWebhookUrl,
            allowedEventTypes: '$pageView, $autoCapture, $customEvent1',
        },
        global: {},
        fetch: fetchMock as unknown,
    } as PatternsMeta
    setupPlugin(meta)

    const event = createEvent({ event: '$pageView' })
    // @ts-ignore
    await onEvent(event, meta)
    expect(fetchMock.mock.calls.length).toEqual(1)
    expect(fetchMock.mock.calls[0][0]).toEqual(testWebhookUrl)
    expect(fetchMock.mock.calls[0][1]).toEqual({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([event]),
    })

    const event2 = createEvent({ event: '$pageLeave' })
    // @ts-ignore
    await onEvent(event2, meta)
    expect(fetchMock.mock.calls.length).toEqual(1)
})
