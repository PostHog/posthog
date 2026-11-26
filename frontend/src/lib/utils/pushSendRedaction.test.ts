import { redactPushSendsInReplay } from './pushSendRedaction'

const BODY = JSON.stringify({ template_id: 't', distinct_id: 'ada', message_data: { code: '123456' } })
const REDACTED = '[SessionRecording] body redacted as it holds the values of a push send'

const recorded = (requests: unknown[]): any => ({
    event: '$snapshot',
    properties: {
        $snapshot_data: [
            { type: 2, data: { node: {} } },
            { type: 6, data: { plugin: 'rrweb/network@1', payload: { requests } } },
        ],
    },
})
const requestsOf = (event: any): any[] => event.properties.$snapshot_data[1].data.payload.requests

describe('push send redaction', () => {
    it.each([
        ['a single send', 'https://us.posthog.com/api/projects/1/messaging/send/push/', REDACTED],
        ['a batch send', '/api/projects/1/messaging/send/push_batch/', REDACTED],
        ['a send with a query', '/api/projects/1/messaging/send/push?x=1', REDACTED],
        ['a broadcast test send', 'https://us.posthog.com/api/projects/1/hog_flows/new/invocations/', REDACTED],
        ['a saved workflow test send', '/api/environments/1/hog_flows/0190-abc/invocations', REDACTED],
        ['the workflow list', '/api/projects/1/hog_flows/', BODY],
        ['an email send', '/api/projects/1/messaging/send/email/', BODY],
        ['the push page', '/api/projects/1/messaging_templates/push/', BODY],
    ])('redacts only the body of a push send: %s', (_name, name, requestBody) => {
        const event = redactPushSendsInReplay(
            recorded([{ name, requestBody: BODY, responseBody: '{"message_id":"m"}' }])
        )

        expect(requestsOf(event)).toEqual([{ name, requestBody, responseBody: '{"message_id":"m"}' }])
    })

    it('leaves an event without a push send as it is', () => {
        const event = recorded([
            { name: '/api/projects/1/insights/', requestBody: BODY },
            { name: '/messaging/send/push/' },
        ])

        expect(redactPushSendsInReplay(event)).toBe(event)
    })
})
