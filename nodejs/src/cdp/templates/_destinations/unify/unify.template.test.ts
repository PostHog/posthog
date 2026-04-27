import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './unify.template'

jest.setTimeout(2 * 60 * 1000)

describe('unify template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const defaultInputs = {
        write_key: 'test-write-key',
        person_attributes: {
            email: '{person.properties.email}',
            first_name: '{person.properties.first_name}',
            last_name: '{person.properties.last_name}',
            title: '{person.properties.title}',
            linkedin_url: '{person.properties.linkedin_url}',
        },
        company_attributes: {
            domain: '{event.properties.company_domain}',
            name: '{event.properties.company_name}',
        },
    }

    const parsePayload = (response: Awaited<ReturnType<typeof tester.invoke>>): Record<string, any> => {
        return parseJSON((response.invocation.queueParameters as any).body)
    }

    it.each([
        {
            description: 'pageview with person email',
            event: {
                uuid: 'event-uuid-001',
                event: '$pageview',
                distinct_id: 'distinct-123',
                timestamp: '2024-01-01T00:00:00Z',
                properties: { $current_url: 'https://example.com', plan: 'pro' },
            },
            personProps: { email: 'person@acme.com', role: 'admin' },
            expectedEmail: 'person@acme.com',
        },
        {
            description: 'custom event with different person',
            event: {
                uuid: 'event-uuid-002',
                event: 'Signed Up',
                distinct_id: 'distinct-456',
                timestamp: '2024-01-02T00:00:00Z',
                properties: { plan: 'enterprise', referrer: 'ads' },
            },
            personProps: { email: 'founder@acme.com', role: 'owner' },
            expectedEmail: 'founder@acme.com',
        },
    ])('sends correct payload for $description', async ({ event, personProps, expectedEmail }) => {
        const response = await tester.invoke(defaultInputs, {
            event,
            person: { properties: personProps },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const queueParams = response.invocation.queueParameters as any
        expect(queueParams.url).toBe('https://analytics.unifygtm.com/api/v1/webhooks/posthog')
        expect(queueParams.method).toBe('POST')
        expect(queueParams.headers).toEqual({
            'Content-Type': 'application/json',
            'X-Write-Key': 'test-write-key',
        })

        const payload = parsePayload(response)
        expect(payload.type).toBe(event.event)
        expect(payload.data).toMatchObject(event)
        expect(payload.person).toEqual({
            email: expectedEmail,
            first_name: null,
            last_name: null,
            title: null,
            linkedin_url: null,
        })
    })

    it('resolves company mapping from event properties', async () => {
        const response = await tester.invoke(defaultInputs, {
            event: {
                uuid: 'event-uuid-003',
                event: 'Company Updated',
                distinct_id: 'distinct-789',
                timestamp: '2024-01-03T00:00:00Z',
                properties: { company_domain: 'acme.com', company_name: 'Acme Inc' },
            },
            person: {
                properties: { email: 'owner@acme.com' },
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const payload = parsePayload(response)
        expect(payload.company).toEqual({
            domain: 'acme.com',
            name: 'Acme Inc',
        })
    })

    it('sends empty person payload when person properties are empty', async () => {
        const response = await tester.invoke(defaultInputs, {
            event: {
                uuid: 'event-uuid-004',
                event: 'Signed Up',
                distinct_id: 'distinct-999',
                timestamp: '2024-01-04T00:00:00Z',
                properties: {},
            },
            person: {
                properties: {},
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const payload = parsePayload(response)
        expect(payload.person).toEqual({
            email: null,
            first_name: null,
            last_name: null,
            title: null,
            linkedin_url: null,
        })
    })

    it('allows empty attribute dictionaries', async () => {
        const response = await tester.invoke({
            write_key: 'test-write-key',
            person_attributes: {},
            company_attributes: {},
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const payload = parsePayload(response)
        expect(payload.person).toEqual({})
        expect(payload.company).toEqual({})
    })

    it.each(['$groupidentify', '$set', '$web_vitals'])('skips unsupported event type %s', async (eventName) => {
        const response = await tester.invoke(defaultInputs, {
            event: {
                event: eventName,
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeFalsy()
        expect(response.logs.some((log) => log.message.includes('Skipping unsupported event type'))).toBe(true)
    })

    it('throws when write key is missing', async () => {
        const response = await tester.invoke({ ...defaultInputs, write_key: '' })

        expect(response.finished).toBe(true)
        expect(response.error).toContain('Unify write key is required.')
    })

    it('throws on API error response', async () => {
        const response = await tester.invoke(defaultInputs)
        expect(response.finished).toBe(false)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'invalid request' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatch('Error from Unify API: 400')
    })

    it('completes successfully on 200 response', async () => {
        const response = await tester.invoke(defaultInputs)
        expect(response.finished).toBe(false)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: {},
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
})
