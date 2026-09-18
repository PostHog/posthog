import { parseJSON } from '../../../../common/utils/json-parse'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './pagerduty.template'

const US_ENDPOINT = 'https://events.pagerduty.com/v2/enqueue'
const EU_ENDPOINT = 'https://events.eu.pagerduty.com/v2/enqueue'

describe('pagerduty template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const baseInputs = {
        routing_key: '0123456789abcdef0123456789abcdef',
        region: 'us',
        event_action: 'trigger',
        dedup_key: 'posthog-alert-alert-1',
        summary: 'Log alert Errors is firing: 120 logs in 5m',
        source: 'My project',
        severity: 'critical',
        custom_details: { 'Threshold breached': '120 logs in 5m' },
        links: [{ href: 'https://example.com/logs', text: 'View logs' }],
        client_url: 'https://example.com/logs',
    }

    const bodyOf = (queueParameters: any): Record<string, any> => parseJSON(queueParameters.body)

    it('sends a complete Events API v2 event', async () => {
        const response = await tester.invoke(baseInputs)

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchObject({
            type: 'fetch',
            url: US_ENDPOINT,
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        })
        expect(bodyOf(response.invocation.queueParameters)).toEqual({
            routing_key: '0123456789abcdef0123456789abcdef',
            event_action: 'trigger',
            dedup_key: 'posthog-alert-alert-1',
            payload: {
                summary: 'Log alert Errors is firing: 120 logs in 5m',
                source: 'My project',
                severity: 'critical',
                custom_details: { 'Threshold breached': '120 logs in 5m' },
            },
            client: 'PostHog',
            client_url: 'https://example.com/logs',
            links: [{ href: 'https://example.com/logs', text: 'View logs' }],
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 202,
            body: { status: 'success', dedup_key: 'posthog-alert-alert-1' },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it.each([
        ['us', US_ENDPOINT],
        ['eu', EU_ENDPOINT],
    ])('sends events for the %s region to %s', async (region, expectedEndpoint) => {
        const response = await tester.invoke({ ...baseInputs, region })

        expect(response.error).toBeUndefined()
        expect((response.invocation.queueParameters as any).url).toEqual(expectedEndpoint)
    })

    it('leaves empty optional inputs out of the event', async () => {
        const response = await tester.invoke({
            ...baseInputs,
            dedup_key: '',
            custom_details: {},
            links: [],
            client_url: '',
        })

        expect(response.error).toBeUndefined()
        const body = bodyOf(response.invocation.queueParameters)
        expect(body).not.toHaveProperty('dedup_key')
        expect(body).not.toHaveProperty('links')
        expect(body).not.toHaveProperty('client_url')
        expect(body.payload).not.toHaveProperty('custom_details')
    })

    it('fails the run when PagerDuty rejects the event', async () => {
        let response = await tester.invoke(baseInputs)
        response = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { status: 'invalid event' },
        })

        expect(response.error).toContain('Failed to send event to PagerDuty: 400')
    })
})
