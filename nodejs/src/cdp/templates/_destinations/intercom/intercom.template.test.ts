import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './intercom.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    oauth: { access_token: 'ACCESS_TOKEN', 'app.region': 'US' },
    email: 'max@posthog.com',
    include_all_properties: false,
    properties: { name: 'Max AI', phone: '+1234567890', last_seen_at: '1234567890' },
    customProperties: {},
    ...overrides,
})

describe('intercom template', () => {
    const tester = new TemplateTester(template)

    const parseBody = (response: any): Record<string, any> => parseJSON(response.invocation.queueParameters.body)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    /* Every run searches for the contact first, then creates or updates it. */
    const search = async (inputs = createInputs(), globals?: any): Promise<any> => {
        const response = await tester.invoke(inputs, globals)
        expect(response.error).toBeUndefined()
        return response
    }

    it('searches, then creates a contact that does not exist', async () => {
        const response = await search()

        expect((response.invocation.queueParameters as any).url).toEqual('https://api.intercom.io/contacts/search')
        expect(parseBody(response)).toEqual({
            query: { field: 'email', operator: '=', value: 'max@posthog.com' },
        })

        const created = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { total_count: 0 },
        })

        expect(created.error).toBeUndefined()
        expect((created.invocation.queueParameters as any).url).toEqual('https://api.intercom.io/contacts')
        expect((created.invocation.queueParameters as any).method).toEqual('POST')
        expect(parseBody(created)).toEqual({
            email: 'max@posthog.com',
            custom_attributes: {},
            name: 'Max AI',
            phone: '+1234567890',
            last_seen_at: '1234567890',
        })

        const done = await tester.invokeFetchResponse(created.invocation, { status: 200, body: { id: '1' } })
        expect(done.error).toBeUndefined()
        expect(done.finished).toBe(true)
    })

    it('updates the contact when one already exists', async () => {
        const response = await search()
        const updated = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { total_count: 1, data: [{ id: '123' }] },
        })

        expect((updated.invocation.queueParameters as any).url).toEqual('https://api.intercom.io/contacts/123')
        expect((updated.invocation.queueParameters as any).method).toEqual('PUT')
    })

    it('sends person properties when include_all_properties is on', async () => {
        const response = await search(createInputs({ include_all_properties: true }), {
            person: { properties: { $geoip_country_name: 'United States', plan: 'pay-as-you-go' } },
        })
        const created = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { total_count: 0 },
        })

        const body = parseBody(created)
        expect(body.plan).toEqual('pay-as-you-go')
        /* $-prefixed person properties are PostHog internals and stay out of the payload. */
        expect(body.$geoip_country_name).toBeUndefined()
    })

    it('skips the request when email is empty', async () => {
        const response = await tester.invoke(createInputs({ email: '' }))

        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'No email set. Skipping...'
        )
    })

    it('throws when the search fails', async () => {
        const response = await search()
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'error' },
        })

        expect(result.error).toEqual("Error from intercom api (status 400): {'error': 'error'}")
    })

    it('throws when the write fails', async () => {
        const response = await search()
        const created = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { total_count: 0 },
        })
        const result = await tester.invokeFetchResponse(created.invocation, {
            status: 400,
            body: { error: 'error' },
        })

        expect(result.error).toEqual("Error from intercom api (status 400): {'error': 'error'}")
    })

    it('throws when the email matches more than one contact', async () => {
        const response = await search()
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { total_count: 2, data: [{ id: '1' }, { id: '2' }] },
        })

        expect(result.error).toEqual('Found multiple contacts with the same email address. Skipping...')
    })
})
