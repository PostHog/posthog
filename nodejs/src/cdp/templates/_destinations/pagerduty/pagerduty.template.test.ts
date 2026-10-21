import { CyclotronJobInvocationResult } from '~/cdp/types'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './pagerduty.template'

const ENQUEUE_URL = 'https://events.pagerduty.com/v2/enqueue'

describe('pagerduty template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const inputs = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
        routing_key: 'abcdef0123456789abcdef0123456789',
        event_action: 'trigger',
        dedup_key: 'posthog-alert-1',
        summary: 'Log alert Checkout errors is firing',
        source: 'My project',
        severity: 'critical',
        component: 'logs alert',
        event_class: 'firing',
        custom_details: { threshold: 100 },
        links: [{ href: 'https://example.com/alert', text: 'View alert' }],
        ...overrides,
    })

    const sentBody = (response: CyclotronJobInvocationResult): Record<string, any> => {
        const params = response.invocation.queueParameters as { body: string }
        return parseJSON(params.body)
    }

    it('sends a trigger as an Events API v2 event', async () => {
        const response = await tester.invoke(inputs())

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchObject({
            type: 'fetch',
            url: ENQUEUE_URL,
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        })
        expect(sentBody(response)).toEqual({
            routing_key: 'abcdef0123456789abcdef0123456789',
            event_action: 'trigger',
            dedup_key: 'posthog-alert-1',
            payload: {
                summary: 'Log alert Checkout errors is firing',
                source: 'My project',
                severity: 'critical',
                component: 'logs alert',
                class: 'firing',
                custom_details: { threshold: 100 },
            },
            client: 'PostHog',
            links: [{ href: 'https://example.com/alert', text: 'View alert' }],
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 202,
            body: { status: 'success', dedup_key: 'posthog-alert-1' },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('leaves out empty optional fields on a trigger', async () => {
        const response = await tester.invoke(
            inputs({ dedup_key: '', component: '', event_class: '', custom_details: {}, links: [] })
        )

        const body = sentBody(response)
        expect(body).not.toHaveProperty('dedup_key')
        expect(body).not.toHaveProperty('links')
        expect(body.payload).toEqual({
            summary: 'Log alert Checkout errors is firing',
            source: 'My project',
            severity: 'critical',
        })
    })

    it.each(['resolve', 'acknowledge'])('sends only the key fields for %s', async (action) => {
        const response = await tester.invoke(inputs({ event_action: action }))

        expect(sentBody(response)).toEqual({
            routing_key: 'abcdef0123456789abcdef0123456789',
            event_action: action,
            dedup_key: 'posthog-alert-1',
        })
    })

    it.each(['resolve', 'acknowledge'])('needs a dedup key to %s an incident', async (action) => {
        const response = await tester.invoke(inputs({ event_action: action, dedup_key: '' }))

        expect(response.error).toContain(`A dedup key is required to ${action} an incident.`)
        expect(response.invocation.queueParameters).toBeFalsy()
    })

    it.each(['high', '', null])('sends the unknown severity %p as error', async (severity) => {
        const response = await tester.invoke(inputs({ severity }))

        expect(sentBody(response).payload.severity).toBe('error')
    })

    it.each([
        ['the event property when it is set', 'checkout-api', 'checkout-api'],
        ['the project name when the event property is empty', '', 'project-name'],
        ['the project name when the event property is missing', undefined, 'project-name'],
    ])('defaults the source to %s', async (_label, eventSource, expected) => {
        const { source: _omitted, ...withoutSource } = inputs()
        const response = await tester.invoke(
            withoutSource,
            eventSource === undefined ? {} : { event: { properties: { source: eventSource } } }
        )

        expect(sentBody(response).payload.source).toBe(expected)
    })

    it.each(['', null])('sends a fallback source when the source renders as %p', async (source) => {
        const response = await tester.invoke(inputs({ source }))

        expect(sentBody(response).payload.source).toBe('PostHog')
    })

    it.each([
        ['us', ENQUEUE_URL],
        ['eu', 'https://events.eu.pagerduty.com/v2/enqueue'],
    ])('posts to the %s endpoint', async (region, url) => {
        const response = await tester.invoke(inputs({ region }))

        expect(response.invocation.queueParameters).toMatchObject({ url })
    })

    it('cuts the summary to the PagerDuty limit', async () => {
        const response = await tester.invoke(inputs({ summary: 'x'.repeat(1100) }))

        expect(sentBody(response).payload.summary).toHaveLength(1024)
    })

    it('rejects an unknown event action', async () => {
        const response = await tester.invoke(inputs({ event_action: 'page' }))

        expect(response.error).toContain('Unsupported event action "page". Use trigger, acknowledge or resolve.')
    })

    it.each([400, 302])('fails when PagerDuty answers with status %p', async (status) => {
        const response = await tester.invoke(inputs())

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status,
            body: { status: 'invalid event', message: 'Event object is invalid' },
        })

        expect(fetchResponse.error).toContain(`PagerDuty rejected the event: ${status}`)
    })
})
