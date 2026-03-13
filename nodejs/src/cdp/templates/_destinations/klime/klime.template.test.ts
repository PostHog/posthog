import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './klime.template'

jest.setTimeout(2 * 60 * 1000)

describe('klime template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const defaultInputs = {
        writeKey: 'test-write-key',
        action: 'automatic',
        userId: 'user-123',
        groupId: '',
        include_all_properties: false,
        properties: {},
    }

    const parseBatchEvent = (response: Awaited<ReturnType<typeof tester.invoke>>): Record<string, any> => {
        const body = parseJSON((response.invocation.queueParameters as any).body)
        return body.batch[0]
    }

    it('sends a track event with correct shape', async () => {
        const response = await tester.invoke(defaultInputs, {
            event: {
                uuid: 'event-uuid-001',
                event: 'Button Clicked',
                properties: { $current_url: 'https://example.com', button: 'signup' },
                timestamp: '2024-01-01T00:00:00Z',
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const queueParams = response.invocation.queueParameters as any
        expect(queueParams.url).toBe('https://i.klime.com/v1/batch')
        expect(queueParams.method).toBe('POST')
        expect(queueParams.headers).toEqual({
            'Content-Type': 'application/json',
            Authorization: 'Bearer test-write-key',
        })

        const batchEvent = parseBatchEvent(response)
        expect(batchEvent).toMatchObject({
            type: 'track',
            messageId: 'event-uuid-001',
            timestamp: '2024-01-01T00:00:00Z',
            userId: 'user-123',
            event: 'Button Clicked',
            context: { library: { name: 'posthog-cdp', version: '1.0.0' } },
        })
        expect(batchEvent.properties).toBeUndefined()
    })

    it.each([
        ['$identify', 'identify'],
        ['$set', 'identify'],
        ['$groupidentify', 'group'],
        ['custom_event', 'track'],
        ['$pageview', 'track'],
    ])('automatic action maps %s to %s', async (eventName, expectedType) => {
        const response = await tester.invoke(
            { ...defaultInputs, groupId: 'group-123' },
            {
                event: {
                    uuid: 'uuid-1',
                    event: eventName,
                    properties: {},
                    timestamp: '2024-01-01T00:00:00Z',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(parseBatchEvent(response).type).toBe(expectedType)
    })

    it('forced action overrides automatic mapping', async () => {
        const response = await tester.invoke(
            { ...defaultInputs, action: 'track' },
            {
                event: {
                    uuid: 'uuid-1',
                    event: '$identify',
                    properties: {},
                    timestamp: '2024-01-01T00:00:00Z',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(parseBatchEvent(response).type).toBe('track')
    })

    it('includes non-$ event properties when include_all_properties is true for track', async () => {
        const response = await tester.invoke(
            { ...defaultInputs, include_all_properties: true },
            {
                event: {
                    uuid: 'uuid-1',
                    event: 'Purchase',
                    properties: { $lib: 'web', amount: 99.99, currency: 'USD' },
                    timestamp: '2024-01-01T00:00:00Z',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(parseBatchEvent(response).properties).toEqual({ amount: 99.99, currency: 'USD' })
    })

    it('includes non-$ person properties when include_all_properties is true for identify', async () => {
        const response = await tester.invoke(
            { ...defaultInputs, action: 'identify', include_all_properties: true },
            {
                event: {
                    uuid: 'uuid-1',
                    event: '$identify',
                    properties: {},
                    timestamp: '2024-01-01T00:00:00Z',
                },
                person: {
                    properties: { email: 'test@klime.com', $creator_event_uuid: 'x' },
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(parseBatchEvent(response).traits).toEqual({ email: 'test@klime.com' })
    })

    it('includes non-$ group_set properties when include_all_properties is true for group', async () => {
        const response = await tester.invoke(
            { ...defaultInputs, action: 'group', groupId: 'org-456', include_all_properties: true },
            {
                event: {
                    uuid: 'uuid-1',
                    event: '$group_identify',
                    properties: {
                        $group_type: 'account',
                        $group_key: 'org-456',
                        $group_set: { name: 'Acme Inc', plan: 'enterprise', $initial_os: 'Mac OS X' },
                    },
                    timestamp: '2024-01-01T00:00:00Z',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(parseBatchEvent(response).traits).toEqual({ name: 'Acme Inc', plan: 'enterprise' })
    })

    it('sends custom property mapping as properties on track events', async () => {
        const response = await tester.invoke({
            ...defaultInputs,
            properties: { plan: 'enterprise', source: 'posthog' },
        })

        expect(response.error).toBeUndefined()
        expect(parseBatchEvent(response).properties).toEqual({ plan: 'enterprise', source: 'posthog' })
    })

    it('skips and logs when identify action has no user ID', async () => {
        const response = await tester.invoke({ ...defaultInputs, action: 'identify', userId: '' })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeFalsy()
        expect(response.logs.some((log) => log.message.includes('No user ID set.'))).toBe(true)
    })

    it('skips and logs when group action has no group ID', async () => {
        const response = await tester.invoke({ ...defaultInputs, action: 'group', groupId: '' })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeFalsy()
        expect(response.logs.some((log) => log.message.includes('No group ID set.'))).toBe(true)
    })

    it('throws on API error response', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.finished).toBe(false)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'invalid request' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatch('Error from Klime API: 400')
    })
})
