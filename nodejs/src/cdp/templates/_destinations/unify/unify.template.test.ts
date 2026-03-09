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
        person_mapping: {
            email: '{person.properties.email}',
            first_name: '{person.properties.first_name}',
            last_name: '{person.properties.last_name}',
            title: '{person.properties.title}',
            linkedin_url: '{person.properties.linkedin_url}',
        },
        company_properties: {
            domain: '{event.properties.company_domain}',
            name: '{event.properties.company_name}',
        },
    }

    const parsePayload = (response: Awaited<ReturnType<typeof tester.invoke>>): Record<string, any> => {
        return parseJSON((response.invocation.queueParameters as any).body)
    }

    it('sends event, person, and resolved mapping payload', async () => {
        const response = await tester.invoke(defaultInputs, {
            event: {
                uuid: 'event-uuid-001',
                event: '$pageview',
                distinct_id: 'distinct-123',
                timestamp: '2024-01-01T00:00:00Z',
                properties: { $current_url: 'https://example.com', plan: 'pro' },
            },
            person: {
                properties: { email: 'person@acme.com', role: 'admin' },
            },
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
        expect(payload.type).toBe('$pageview')
        expect(payload.data).toMatchObject({
            uuid: 'event-uuid-001',
            event: '$pageview',
            distinct_id: 'distinct-123',
            timestamp: '2024-01-01T00:00:00Z',
            properties: { $current_url: 'https://example.com', plan: 'pro' },
        })
        expect(payload.person).toEqual({
            email: 'person@acme.com',
            properties: { email: 'person@acme.com', role: 'admin' },
        })
        expect(payload.mapping).toEqual({
            person: {
                email: 'person@acme.com',
                first_name: null,
                last_name: null,
                title: null,
                linkedin_url: null,
            },
            company: {
                domain: null,
                name: null,
            },
        })
    })

    it('sends event data and person object', async () => {
        const response = await tester.invoke(defaultInputs, {
            event: {
                uuid: 'event-uuid-002',
                event: 'Signed Up',
                distinct_id: 'distinct-456',
                timestamp: '2024-01-02T00:00:00Z',
                properties: { plan: 'enterprise', referrer: 'ads' },
            },
            person: {
                properties: { email: 'founder@acme.com', role: 'owner' },
            },
        })

        expect(response.error).toBeUndefined()

        const payload = parsePayload(response)
        expect(payload.data).toMatchObject({
            uuid: 'event-uuid-002',
            event: 'Signed Up',
            distinct_id: 'distinct-456',
            timestamp: '2024-01-02T00:00:00Z',
            properties: { plan: 'enterprise', referrer: 'ads' },
        })
        expect(payload.person).toEqual({
            email: 'founder@acme.com',
            properties: { email: 'founder@acme.com', role: 'owner' },
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
        expect(payload.mapping.company).toEqual({
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
            properties: {},
        })
    })

    it('allows empty mapping dictionaries', async () => {
        const response = await tester.invoke({
            write_key: 'test-write-key',
            person_mapping: {},
            company_properties: {},
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const payload = parsePayload(response)
        expect(payload.mapping).toEqual({
            person: {},
            company: {},
        })
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
})
