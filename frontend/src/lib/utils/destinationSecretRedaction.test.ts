import { redactDestinationSecrets, redactDestinationSecretsInReplay } from './destinationSecretRedaction'

const WEBHOOK = 'https://hooks.example.com/services/T000/B000/fake-secret-path'

describe('destination secret redaction', () => {
    it.each([
        [
            'a nested webhook URL',
            { destinations: [{ type: 'slack', webhook_url: WEBHOOK, enabled: true }] },
            { destinations: [{ type: 'slack', webhook_url: 'redacted', enabled: true }] },
        ],
        [
            'a PagerDuty routing key',
            { type: 'pagerduty', pagerduty_routing_key: 'fake0000routing0000key', pagerduty_severity: 'error' },
            { type: 'pagerduty', pagerduty_routing_key: 'redacted', pagerduty_severity: 'error' },
        ],
        [
            'a camel-case webhook input with its value',
            { inputs: { webhookUrl: { value: WEBHOOK }, channel: { value: '#alerts' } } },
            { inputs: { webhookUrl: 'redacted', channel: { value: '#alerts' } } },
        ],
        [
            'the URL input of a webhook destination',
            {
                template_id: 'template-webhook',
                inputs: { url: { value: WEBHOOK }, body: { value: { insight_url: '{project.url}/insights/1' } } },
            },
            {
                template_id: 'template-webhook',
                inputs: { url: 'redacted', body: { value: { insight_url: '{project.url}/insights/1' } } },
            },
        ],
    ])('masks %s', (_name, body, expected) => {
        expect(JSON.parse(redactDestinationSecrets(JSON.stringify(body)) as string)).toEqual(expected)
    })

    it.each([
        ['a body with no destination secret', JSON.stringify({ name: 'Errors', threshold: 10, url: WEBHOOK })],
        ['a body that only mentions a field name in a value', JSON.stringify({ description: 'set webhook_url' })],
        ['a body the SDK already scrubbed', '[SessionRecording] Request body redacted as might contain: token'],
    ])('keeps %s byte for byte', (_name, body) => {
        expect(redactDestinationSecrets(body)).toBe(body)
    })

    it.each([
        ['is not JSON', `webhook_url=${encodeURIComponent(WEBHOOK)}`],
        ['nests deeper than the stack allows', `${'['.repeat(10000)}{"webhook_url":"x"}${']'.repeat(10000)}`],
    ])('replaces a body that names a secret field and %s', (_name, body) => {
        expect(redactDestinationSecrets(body)).toBe(
            '[SessionRecording] body redacted as might contain a destination secret'
        )
    })

    it('masks request and response bodies in replay network snapshots and leaves other requests unchanged', () => {
        const unrelated = { name: '/api/projects/1/insights/', requestBody: '{"name":"Errors"}', responseBody: null }
        const event = redactDestinationSecretsInReplay({
            event: '$snapshot',
            properties: {
                $snapshot_data: [
                    { type: 2, data: { node: {} } },
                    {
                        type: 6,
                        data: {
                            plugin: 'rrweb/network@1',
                            payload: {
                                requests: [
                                    unrelated,
                                    {
                                        name: '/api/projects/1/alerts/receivers/',
                                        requestBody: JSON.stringify({ webhook_url: WEBHOOK }),
                                        responseBody: JSON.stringify({ id: 'r1', pagerduty_routing_key: 'fake-key' }),
                                    },
                                ],
                            },
                        },
                    },
                ],
            },
        } as any)

        const [fullSnapshot, network] = event!.properties.$snapshot_data
        const [keptRequest, maskedRequest] = network.data.payload.requests
        expect(fullSnapshot).toEqual({ type: 2, data: { node: {} } })
        expect(keptRequest).toBe(unrelated)
        expect(maskedRequest.requestBody).toBe('{"webhook_url":"redacted"}')
        expect(maskedRequest.responseBody).toBe('{"id":"r1","pagerduty_routing_key":"redacted"}')
    })
})
